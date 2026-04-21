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
	"bytes"
	"errors"
	"io"
	"log/slog"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/apache/airflow/go-sdk/sdk"
)

// --- Test task functions ---

func failingTask() error {
	return errors.New("task failed intentionally")
}

func panicTask() error {
	panic("something went wrong")
}

func simpleTask() error {
	return nil
}

// --- Tests ---

func TestDagParsing(t *testing.T) {
	bundle := sdk.NewBundle("test_bundle", "1.0.0")
	dag := bundle.AddDag("test_dag")
	dag.WithSchedule("0 12 * * *").WithDescription("Test DAG")
	dag.AddTask(simpleTask)

	req := &DagFileParseRequest{
		File:       "/bundles/test/main.go",
		BundlePath: "/bundles/test",
	}

	result := ParseDags(bundle, req)

	assert.Equal(t, "DagFileParsingResult", result["type"])
	assert.Equal(t, "/bundles/test/main.go", result["fileloc"])

	serializedDags, ok := result["serialized_dags"].([]any)
	require.True(t, ok)
	require.Len(t, serializedDags, 1)

	dagEntry := serializedDags[0].(map[string]any)
	data := dagEntry["data"].(map[string]any)
	assert.Equal(t, 3, data["__version"])

	dagMap := data["dag"].(map[string]any)
	assert.Equal(t, "test_dag", dagMap["dag_id"])
	assert.Equal(t, "Test DAG", dagMap["description"])

	// Verify timetable.
	tt := dagMap["timetable"].(map[string]any)
	assert.Equal(t, "airflow.timetables.trigger.CronTriggerTimetable", tt["__type"])

	// Verify tasks.
	tasks := dagMap["tasks"].([]any)
	require.Len(t, tasks, 1)
	taskMap := tasks[0].(map[string]any)
	assert.Equal(t, "operator", taskMap["__type"])
	taskData := taskMap["__var"].(map[string]any)
	assert.Equal(t, "simpleTask", taskData["task_id"])
	assert.Equal(t, "go", taskData["language"])
}

func TestDagParsingMultipleDags(t *testing.T) {
	bundle := sdk.NewBundle("multi_bundle", "2.0")
	bundle.AddDag("dag1").AddTask(simpleTask)
	bundle.AddDag("dag2").AddTask(failingTask)

	req := &DagFileParseRequest{File: "/bundle/main.go", BundlePath: "/bundle"}
	result := ParseDags(bundle, req)

	serializedDags := result["serialized_dags"].([]any)
	require.Len(t, serializedDags, 2)

	dag1Data := serializedDags[0].(map[string]any)["data"].(map[string]any)["dag"].(map[string]any)
	assert.Equal(t, "dag1", dag1Data["dag_id"])

	dag2Data := serializedDags[1].(map[string]any)["data"].(map[string]any)["dag"].(map[string]any)
	assert.Equal(t, "dag2", dag2Data["dag_id"])
}

func TestTaskRunnerSuccess(t *testing.T) {
	bundle := sdk.NewBundle("test", "1.0")
	bundle.AddDag("test_dag").AddTask(simpleTask)

	details := &StartupDetails{
		TI: TaskInstanceInfo{
			ID:       "550e8400-e29b-41d4-a716-446655440000",
			DagID:    "test_dag",
			TaskID:   "simpleTask",
			RunID:    "run1",
			MapIndex: -1,
		},
		BundleInfo: BundleInfoMsg{Name: "test", Version: "1.0"},
	}

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	comm := NewCoordinatorComm(bytes.NewReader(nil), io.Discard, logger)

	result := RunTask(bundle, details, comm, logger)
	assert.Equal(t, "SucceedTask", result["type"])
}

func TestTaskRunnerFailure(t *testing.T) {
	bundle := sdk.NewBundle("test", "1.0")
	bundle.AddDag("test_dag").AddTask(failingTask)

	details := &StartupDetails{
		TI: TaskInstanceInfo{
			ID:       "550e8400-e29b-41d4-a716-446655440000",
			DagID:    "test_dag",
			TaskID:   "failingTask",
			RunID:    "run1",
			MapIndex: -1,
		},
		BundleInfo: BundleInfoMsg{Name: "test", Version: "1.0"},
	}

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	comm := NewCoordinatorComm(bytes.NewReader(nil), io.Discard, logger)

	result := RunTask(bundle, details, comm, logger)
	assert.Equal(t, "TaskState", result["type"])
	assert.Equal(t, "failed", result["state"])
}

func TestTaskRunnerTaskNotFound(t *testing.T) {
	bundle := sdk.NewBundle("test", "1.0")
	bundle.AddDag("test_dag").AddTask(simpleTask)

	details := &StartupDetails{
		TI: TaskInstanceInfo{
			ID:     "550e8400-e29b-41d4-a716-446655440000",
			DagID:  "test_dag",
			TaskID: "nonexistent",
			RunID:  "run1",
		},
		BundleInfo: BundleInfoMsg{Name: "test", Version: "1.0"},
	}

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	comm := NewCoordinatorComm(bytes.NewReader(nil), io.Discard, logger)

	result := RunTask(bundle, details, comm, logger)
	assert.Equal(t, "TaskState", result["type"])
	assert.Equal(t, "removed", result["state"])
}

func TestTaskRunnerPanic(t *testing.T) {
	bundle := sdk.NewBundle("test", "1.0")
	bundle.AddDag("test_dag").AddTask(panicTask)

	details := &StartupDetails{
		TI: TaskInstanceInfo{
			ID:       "550e8400-e29b-41d4-a716-446655440000",
			DagID:    "test_dag",
			TaskID:   "panicTask",
			RunID:    "run1",
			MapIndex: -1,
		},
		BundleInfo: BundleInfoMsg{Name: "test", Version: "1.0"},
	}

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	comm := NewCoordinatorComm(bytes.NewReader(nil), io.Discard, logger)

	result := RunTask(bundle, details, comm, logger)
	assert.Equal(t, "TaskState", result["type"])
	assert.Equal(t, "failed", result["state"])
}

func TestBundleGetTask(t *testing.T) {
	bundle := sdk.NewBundle("test", "1.0")
	bundle.AddDag("dag1").AddTask(simpleTask)
	bundle.AddDag("dag2").AddTask(failingTask)

	dag1, ok := bundle.GetDag("dag1")
	require.True(t, ok)
	entry, ok := dag1.GetTask("simpleTask")
	assert.True(t, ok)
	assert.NotNil(t, entry)

	dag2, ok := bundle.GetDag("dag2")
	require.True(t, ok)
	entry, ok = dag2.GetTask("failingTask")
	assert.True(t, ok)
	assert.NotNil(t, entry)

	_, ok = dag1.GetTask("nonexistent")
	assert.False(t, ok)

	_, ok = bundle.GetDag("nonexistent_dag")
	assert.False(t, ok)
}

func TestDagDefDownstream(t *testing.T) {
	bundle := sdk.NewBundle("test", "1.0")
	dag := bundle.AddDag("pipeline")
	dag.AddTask(simpleTask)
	dag.AddTaskWithName("transform", failingTask)
	dag.SetDownstream("simpleTask", "transform")

	req := &DagFileParseRequest{File: "/bundle/main.go", BundlePath: "/bundle"}
	result := ParseDags(bundle, req)

	serializedDags := result["serialized_dags"].([]any)
	dagData := serializedDags[0].(map[string]any)["data"].(map[string]any)["dag"].(map[string]any)

	tasks := dagData["tasks"].([]any)
	require.Len(t, tasks, 2)

	for _, task := range tasks {
		taskMap := task.(map[string]any)["__var"].(map[string]any)
		if taskMap["task_id"] == "simpleTask" {
			downstream := taskMap["downstream_task_ids"].([]string)
			assert.Equal(t, []string{"transform"}, downstream)
		}
	}
}

func TestParseArgs(t *testing.T) {
	t.Run("valid args", func(t *testing.T) {
		comm, logs, err := parseArgs([]string{"--comm=127.0.0.1:5000", "--logs=127.0.0.1:5001"})
		require.NoError(t, err)
		assert.Equal(t, "127.0.0.1:5000", comm)
		assert.Equal(t, "127.0.0.1:5001", logs)
	})

	t.Run("missing comm", func(t *testing.T) {
		_, _, err := parseArgs([]string{"--logs=127.0.0.1:5001"})
		assert.Error(t, err)
		assert.Contains(t, err.Error(), "--comm")
	})

	t.Run("missing logs", func(t *testing.T) {
		_, _, err := parseArgs([]string{"--comm=127.0.0.1:5000"})
		assert.Error(t, err)
		assert.Contains(t, err.Error(), "--logs")
	})

	t.Run("extra args ignored", func(t *testing.T) {
		comm, logs, err := parseArgs([]string{
			"--other=flag",
			"--comm=localhost:9000",
			"--logs=localhost:9001",
			"positional",
		})
		require.NoError(t, err)
		assert.Equal(t, "localhost:9000", comm)
		assert.Equal(t, "localhost:9001", logs)
	})
}
