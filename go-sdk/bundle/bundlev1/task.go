// Licensed to the Apache Software Foundation (ASF) under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
// KIND, either express or implied.  See the License for the
// specific language governing permissions and limitations
// under the License.

package bundlev1

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"reflect"
	"runtime"

	"github.com/go-viper/mapstructure/v2"

	"github.com/apache/airflow/go-sdk/pkg/api"
	"github.com/apache/airflow/go-sdk/sdk"
)

type taskFunction struct {
	fn       reflect.Value
	fullName string

	sdk.Client
	TIRunState *api.TIRunState
	api.ExecuteTaskWorkload
}

var _ Task = (*taskFunction)(nil)

func NewTaskFunction(fn any) (Task, error) {
	v := reflect.ValueOf(fn)
	fullName := runtime.FuncForPC(v.Pointer()).Name()
	f := &taskFunction{fn: v, fullName: fullName}
	return f, f.validateFn(v.Type())
}

func (f *taskFunction) Execute(
	ctx context.Context,
	logger *slog.Logger,
	workload api.ExecuteTaskWorkload,
	runtimeState *api.TIRunContext,
) error {
	f.Client = sdk.NewClient()
	f.TIRunState = runtimeState
	f.ExecuteTaskWorkload = workload

	var err error

	reflectArgs, err := f.bindArgs(ctx, logger)

	slog.Debug("Attempting to call fn", "fn", f.fn, "args", reflectArgs)
	retValues := f.fn.Call(reflectArgs)

	if errResult := retValues[len(retValues)-1].Interface(); errResult != nil {
		var ok bool
		if err, ok = errResult.(error); !ok {
			return fmt.Errorf(
				"failed to extract task error result as it is not of error interface: %v",
				errResult,
			)
		}
	}
	// If there are two results, convert the first only if it's not a nil pointer
	if len(retValues) > 1 && (retValues[0].Kind() != reflect.Ptr || !retValues[0].IsNil()) {
		res := retValues[0].Interface()
		f.sendXcom(ctx, res, logger)
	}
	return err
}

func (f *taskFunction) bindArgs(ctx context.Context, logger *slog.Logger) ([]reflect.Value, error) {
	fnType := f.fn.Type()

	var taskArgs []api.JsonValue
	if f.TIRunState.TaskArgs != nil {
		taskArgs = *f.TIRunState.TaskArgs
	}

	reflectArgs := make([]reflect.Value, fnType.NumIn())
	// Keep track of if we are in "task params" (i.e. arguments that appear in the `@task.stub` in the DAG), or
	// in the known types (which is somewhat analogous to the "known kwarg names" to pull out values from the
	// python task context to FN args)
	inSpecialArguments := true

	for i := range reflectArgs {
		in := fnType.In(i)

		if inSpecialArguments {
			switch {
			case isContext(in):
				reflectArgs[i] = reflect.ValueOf(ctx)
			case isLogger(in):
				reflectArgs[i] = reflect.ValueOf(logger)
			case isClient(in):
				reflectArgs[i] = reflect.ValueOf(f.Client)
			default:
				// We're now into task parameters
				inSpecialArguments = false
			}

			if reflectArgs[i].IsValid() {
				// We populate this one, move to next argument
				continue
			}
		}
		if !inSpecialArguments {
			if isContext(in) || isLogger(in) || isClient(in) {
				errStr := "Go operator definition error, task arguments must come after all 'known types'"
				slog.ErrorContext(ctx, errStr, "position", i, "argument_type", in.String())
				return nil, fmt.Errorf("%s for argument %d in function %s", errStr, i, f.fullName)
			}

			if len(taskArgs) == 0 {
				errStr := "Not enough arguments to task function"
				slog.ErrorContext(ctx, errStr, "position", i, "argument_type", in.String())
				return nil, errors.New(errStr)
			}

			var err error
			reflectArgs[i], taskArgs, err = f.reflectArgFromRuntimeContext(ctx, in, taskArgs)
			if err != nil {
				slog.ErrorContext(
					ctx,
					"Unable to create argument from runtime context",
					"position",
					i,
					"argument_type",
					in.String(),
					"err",
					err,
				)
				return nil, err
			}
		}

	}

	return reflectArgs, nil
}

const XComArgType = "XComArg"

type xcomArgRepr struct {
	Type string `json:"__type"`
	Var  struct {
		TaskID string `json:"task_id"`
		Key    string `json:"key"`
	} `json:"__var"`
}

func (f *taskFunction) reflectArgFromRuntimeContext(
	ctx context.Context,
	in reflect.Type,
	taskArgs []api.JsonValue,
) (reflect.Value, []api.JsonValue, error) {
	// TODO:Handle a struct parameter to pull in all arguments? Does this need to be the only argument left
	// perhaops

	// Json decode it, then see what value we are given.
	buf, err := taskArgs[0].MarshalJSON()
	if err != nil {
		// This "should" never happen, as it's already been JSON parsed to get the RawMEssage object. But lets be
		// safe
		return reflect.Value{}, nil, err
	}
	taskArgs = taskArgs[1:]

	// This is a bit convoluted, but before we try and decode into the arg value type, we first need to see if
	// the type is Airflow serde, so we try to decode it as such
	var xcomArg xcomArgRepr
	dec := json.NewDecoder(bytes.NewReader(buf))
	dec.DisallowUnknownFields()
	dec.UseNumber()
	if err = dec.Decode(&xcomArg); err == nil && xcomArg.Type == XComArgType {
		// TODO: Future optimization: parallelise pulling these xcom values

		// TODO: Look up at upstream map indexes

		if xcomArg.Var.Key == "" {
			xcomArg.Var.Key = api.XComReturnValueKey
		}

		xcomVal, err := f.Client.GetXCom(
			ctx,
			f.TI.DagId,
			f.TI.RunId,
			xcomArg.Var.TaskID,
			nil,
			xcomArg.Var.Key,
		)
		if err != nil {
			return reflect.Value{}, nil, fmt.Errorf("unable to get xcom value %w", err)
		}
		// TODO: Sort this out. Don't xcom deser it early!
		buf, _ = json.Marshal(xcomVal)
	}

	argVal := reflect.New(in).Interface()

	err = json.Unmarshal(buf, argVal)

	targetErr := &json.UnmarshalTypeError{}
	if errors.As(err, &targetErr) {
		// For example, trying to decode 42.0 into an int
		// Lets try using mapstrucutre
		var tmp any
		_ = json.Unmarshal(buf, &tmp)

		err = mapstructure.Decode(tmp, argVal)
	}
	if err != nil {
		return reflect.Value{}, nil, err
	}
	realVal := reflect.ValueOf(argVal).Elem()

	return realVal, taskArgs, nil
}

func (f *taskFunction) sendXcom(
	ctx context.Context,
	value any,
	logger *slog.Logger,
) {
	err := f.Client.PutXComForTi(ctx, f.TI, api.XComReturnValueKey, value)
	if err != nil {
		logger.ErrorContext(ctx, "Unable to set XCom", "err", err)
	}
}

func (f *taskFunction) validateFn(fnType reflect.Type) error {
	if fnType.Kind() != reflect.Func {
		return fmt.Errorf("expected a func as input but was %s", fnType.Kind())
	}

	// Return values
	//     `<result>, error`,  or just `error`
	if fnType.NumOut() < 1 || fnType.NumOut() > 2 {
		return fmt.Errorf(
			"task function %s has %d return values, must be `<result>, error` or just `error`",
			f.fullName,
			fnType.NumOut(),
		)
	}
	if fnType.NumOut() > 1 && !isValidResultType(fnType.Out(0)) {
		return fmt.Errorf(
			"expected task function %s first return value to return valid type but found: %v",
			f.fullName,
			fnType.Out(0).Kind(),
		)
	}
	if !isError(fnType.Out(fnType.NumOut() - 1)) {
		return fmt.Errorf(
			"expected task function %s last return value to return error but found %v",
			f.fullName,
			fnType.Out(fnType.NumOut()-1).Kind(),
		)
	}
	return nil
}

func isValidResultType(inType reflect.Type) bool {
	// https://golang.org/pkg/reflect/#Kind
	switch inType.Kind() {
	case reflect.Func, reflect.Chan, reflect.UnsafePointer:
		return false
	}

	return true
}

var (
	errorType      = reflect.TypeFor[error]()
	contextType    = reflect.TypeFor[context.Context]()
	slogLoggerType = reflect.TypeFor[*slog.Logger]()

	connClientType = reflect.TypeFor[sdk.ConnectionClient]()
	varClientType  = reflect.TypeFor[sdk.VariableClient]()
	clientType     = reflect.TypeFor[sdk.Client]()
)

func isError(inType reflect.Type) bool {
	return inType != nil && inType.Implements(errorType)
}

func isContext(inType reflect.Type) bool {
	return inType != nil && inType.Implements(contextType)
}

func isLogger(inType reflect.Type) bool {
	return inType != nil && inType.AssignableTo(slogLoggerType)
}

func isClient(inType reflect.Type) bool {
	return inType != nil && (inType.AssignableTo(clientType) ||
		inType.AssignableTo(connClientType) ||
		inType.AssignableTo(varClientType))
}
