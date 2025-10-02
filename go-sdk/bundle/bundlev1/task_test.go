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
	"context"
	"log/slog"
	"testing"

	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/suite"

	"github.com/apache/airflow/go-sdk/pkg/api"
	apimock "github.com/apache/airflow/go-sdk/pkg/api/mocks"
	"github.com/apache/airflow/go-sdk/pkg/logging"
	"github.com/apache/airflow/go-sdk/pkg/sdkcontext"
	"github.com/apache/airflow/go-sdk/sdk"
)

// helper to create a pointer
func ptr[T any](v T) *T { return &v }

type TaskSuite struct {
	suite.Suite
}

func TestTaskSuite(t *testing.T) {
	suite.Run(t, &TaskSuite{})
}

func (s *TaskSuite) TestReturnValidation() {
	cases := map[string]struct {
		fn          any
		errContains string
	}{
		"no-ret-values": {
			func() {},
			`func\d+ has 0 return values, must be`,
		},
		"too-many-ret-values": {
			func() (a, b, c int) { return },
			`func\d+ has 3 return values, must be`,
		},
		"invalid-ret": {
			func() (c chan int) { return },
			`func\d+ last return value to return error but found chan`,
		},
	}

	for name, tt := range cases {
		s.Run(name, func() {
			_, err := NewTaskFunction(tt.fn)
			if s.Assert().Error(err) {
				s.Assert().Regexp(tt.errContains, err.Error())
			}
		})
	}
}

func (s *TaskSuite) TestArgumentBinding() {
	ctxKey := struct{ string }{"abc"}
	cases := map[string]struct {
		fn any
	}{
		"no-args": {
			func() error { return nil },
		},
		"context": {
			func(ctx context.Context) error {
				s.Equal("def", ctx.Value(ctxKey))
				return nil
			},
		},
		"context-and-logger": {
			func(ctx context.Context, logger *slog.Logger) error {
				s.Equal("def", ctx.Value(ctxKey))
				s.NotNil(logger)
				return nil
			},
		},
		"client": {
			func(client sdk.Client) error {
				s.NotNil(client)
				return nil
			},
		},
		"var-client": {
			func(client sdk.VariableClient) error {
				s.NotNil(client)
				return nil
			},
		},
		"conn-client": {
			func(client sdk.ConnectionClient) error {
				s.NotNil(client)

				return nil
			},
		},
	}

	for name, tt := range cases {
		s.Run(name, func() {
			task, err := NewTaskFunction(tt.fn)
			s.Require().NoError(err)

			ctx := context.WithValue(context.Background(), ctxKey, "def")
			logger := slog.New(logging.NewTeeLogger())
			task.Execute(ctx, logger, api.ExecuteTaskWorkload{}, &api.TIRunContext{})
		})
	}
}

func (s *TaskSuite) TestArgumentRuntimeParamBinding() {
	workload := api.ExecuteTaskWorkload{
		TI: TaskInstance{
			DagId:     "dag",
			RunId:     "runid",
			TaskId:    "currenttask",
			TryNumber: 1,
		},
	}
	var client api.ClientInterface

	cases := map[string]struct {
		fn any
		api.TIRunState
		setup func()
	}{
		"int-args": {
			func(ctx context.Context, val int) error {
				s.Equal(2, val)
				return nil
			},
			api.TIRunState{
				TaskArgs: ptr([]api.JsonValue{
					api.JsonValueFromBytes([]byte(`2.0`)),
				}),
			},
			nil,
		},
		"xcom-int-arg": {
			func(ctx context.Context, val int) error {
				s.Equal(42, val)
				return nil
			},
			api.TIRunState{
				TaskArgs: ptr([]api.JsonValue{
					api.JsonValueFromBytes([]byte(`
						{"__type": "XComArg", "__var": {"task_id": "upstream1"}}`)),
				}),
			},
			func() {
				mockClient := &apimock.ClientInterface{}
				client = mockClient
				xcoms := &apimock.XcomsClient{}
				mockClient.EXPECT().Xcoms().Return(xcoms)
				xcoms.EXPECT().
					Get(mock.Anything, "dag", "runid", "upstream1", "return_value", mock.Anything).
					Return(&api.XComResponse{
						Key:   "return_value",
						Value: ptr(api.JsonValueFromBytes([]byte(`42.0`))),
					}, nil)

				s.T().Cleanup(func() {
					xcoms.AssertExpectations(s.T())
					mockClient.AssertExpectations(s.T())
				})
			},
		},
	}

	for name, tt := range cases {
		s.Run(name, func() {
			client = nil

			if tt.setup != nil {
				tt.setup()
			}

			ctx := context.WithValue(context.Background(), sdkcontext.ApiClientContextKey, client)

			task, err := NewTaskFunction(tt.fn)
			s.Require().NoError(err)

			logger := slog.New(logging.NewTeeLogger())
			err = task.Execute(ctx, logger, workload, &tt.TIRunState)
			s.NoError(err)
		})
	}
}
