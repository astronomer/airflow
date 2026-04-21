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

package execution

import (
	"context"
	"fmt"
	"log/slog"
	"runtime/debug"
	"time"

	"github.com/google/uuid"

	"github.com/apache/airflow/go-sdk/bundle/bundlev1"
	"github.com/apache/airflow/go-sdk/pkg/api"
	"github.com/apache/airflow/go-sdk/pkg/sdkcontext"
	"github.com/apache/airflow/go-sdk/sdk"
)

// RunTask executes a task based on StartupDetails received from the supervisor.
//
// It looks up the task in the bundle, creates a CoordinatorClient for SDK calls,
// executes the task, and returns a terminal message (SucceedTask or TaskState).
func RunTask(
	bundle *sdk.Bundle,
	details *StartupDetails,
	comm *CoordinatorComm,
	logger *slog.Logger,
) map[string]any {
	// Look up the task entry.
	dag, ok := bundle.GetDag(details.TI.DagID)
	if !ok {
		logger.Error("DAG not found", "dag_id", details.TI.DagID)
		return TaskStateMsg{State: "removed", EndDate: time.Now().UTC()}.toMap()
	}

	entry, ok := dag.GetTask(details.TI.TaskID)
	if !ok {
		logger.Error("Task not found",
			"dag_id", details.TI.DagID,
			"task_id", details.TI.TaskID,
		)
		return TaskStateMsg{State: "removed", EndDate: time.Now().UTC()}.toMap()
	}

	// Convert the raw function to a worker.Task via bundlev1.
	task, err := bundlev1.NewTaskFunction(entry.Fn)
	if err != nil {
		logger.Error("Invalid task function",
			"dag_id", details.TI.DagID,
			"task_id", details.TI.TaskID,
			"error", err,
		)
		return TaskStateMsg{State: "failed", EndDate: time.Now().UTC()}.toMap()
	}

	// Create the CoordinatorClient that implements sdk.Client.
	client := NewCoordinatorClient(comm, details)

	// Build a synthetic ExecuteTaskWorkload for context compatibility.
	// The existing taskFunction.Execute() uses ctx.Value(WorkloadContextKey)
	// to get the task instance info for XCom pushes.
	tiUUID, _ := uuid.Parse(details.TI.ID)
	mapIndex := details.TI.MapIndex
	workload := api.ExecuteTaskWorkload{
		TI: api.TaskInstance{
			Id:        tiUUID,
			DagId:     details.TI.DagID,
			RunId:     details.TI.RunID,
			TaskId:    details.TI.TaskID,
			TryNumber: details.TI.TryNumber,
			MapIndex:  &mapIndex,
		},
		BundleInfo: api.BundleInfo{
			Name:    details.BundleInfo.Name,
			Version: &details.BundleInfo.Version,
		},
	}

	// Build the execution context with all required values.
	ctx := context.Background()
	ctx = context.WithValue(ctx, sdkcontext.WorkloadContextKey, workload)
	ctx = context.WithValue(ctx, sdkcontext.SdkClientContextKey, sdk.Client(client))

	// Execute the task with panic recovery.
	return executeTask(ctx, task, logger)
}

// executeTask runs the task and handles success, failure, and panics.
func executeTask(ctx context.Context, task interface {
	Execute(context.Context, *slog.Logger) error
}, logger *slog.Logger,
) (result map[string]any) {
	defer func() {
		if r := recover(); r != nil {
			logger.Error("Recovered panic in task",
				"error", r,
				"stack", string(debug.Stack()),
			)
			result = TaskStateMsg{
				State:   "failed",
				EndDate: time.Now().UTC(),
			}.toMap()
		}
	}()

	err := task.Execute(ctx, logger)
	if err != nil {
		logger.Error("Task failed", "error", fmt.Sprintf("%v", err))
		return TaskStateMsg{
			State:   "failed",
			EndDate: time.Now().UTC(),
		}.toMap()
	}

	return SucceedTaskMsg{
		EndDate: time.Now().UTC(),
	}.toMap()
}
