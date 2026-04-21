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

package sdk

import (
	"fmt"
	"reflect"
	"runtime"
	"strings"
	"time"
)

const (
	DefaultMaxActiveTasks           = 16
	DefaultMaxActiveRuns            = 16
	DefaultMaxConsecutiveFailedRuns = 0
)

// TaskEntry holds a registered task function and its metadata.
type TaskEntry struct {
	ID       string // Task identifier
	Fn       any    // The raw task function
	TypeName string // Go function name (e.g., "extract")
	PkgPath  string // Go package path (e.g., "main")
}

// DagDef defines a DAG with its metadata and tasks.
// This is the user-facing type for declaring DAGs in coordinator execution mode.
type DagDef struct {
	DagID string

	// Scheduling
	Schedule *string

	// Metadata
	Description    *string
	StartDate      *time.Time
	EndDate        *time.Time
	DagDisplayName *string
	DocMd          *string
	Tags           []string
	OwnerLinks     map[string]string

	// Behavior
	Catchup                   bool
	FailFast                  bool
	MaxActiveTasks            int
	MaxActiveRuns             int
	MaxConsecutiveFailedRuns  int
	DagrunTimeout             *time.Duration
	IsPausedUponCreation      *bool
	RenderTemplateAsNativeObj bool

	// Configuration
	DefaultArgs   map[string]any
	AccessControl map[string]map[string][]string
	Params        map[string]any

	// Tasks (unexported to control ordering)
	tasks      []*TaskEntry
	taskMap    map[string]*TaskEntry
	downstream map[string][]string // taskID -> downstream taskIDs
}

// NewDagDef creates a new DAG definition with default values.
func NewDagDef(dagID string) *DagDef {
	return &DagDef{
		DagID:                    dagID,
		MaxActiveTasks:           DefaultMaxActiveTasks,
		MaxActiveRuns:            DefaultMaxActiveRuns,
		MaxConsecutiveFailedRuns: DefaultMaxConsecutiveFailedRuns,
		taskMap:                  make(map[string]*TaskEntry),
		downstream:               make(map[string][]string),
	}
}

// WithSchedule sets the DAG's schedule expression.
func (d *DagDef) WithSchedule(schedule string) *DagDef {
	d.Schedule = &schedule
	return d
}

// WithDescription sets the DAG description.
func (d *DagDef) WithDescription(desc string) *DagDef {
	d.Description = &desc
	return d
}

// WithStartDate sets the DAG start date.
func (d *DagDef) WithStartDate(t time.Time) *DagDef {
	d.StartDate = &t
	return d
}

// WithTags sets the DAG tags.
func (d *DagDef) WithTags(tags ...string) *DagDef {
	d.Tags = tags
	return d
}

// AddTask registers a task function and infers the task ID from the function name.
func (d *DagDef) AddTask(fn any) *DagDef {
	v := reflect.ValueOf(fn)
	if v.Kind() != reflect.Func {
		panic(fmt.Errorf("task fn was a %s, not a func", v.Kind()))
	}
	fullName := runtime.FuncForPC(v.Pointer()).Name()
	taskID := extractFuncName(fullName)
	d.AddTaskWithName(taskID, fn)
	return d
}

// AddTaskWithName registers a task function with an explicit task ID.
func (d *DagDef) AddTaskWithName(taskID string, fn any) *DagDef {
	if _, exists := d.taskMap[taskID]; exists {
		panic(fmt.Errorf("task %q already registered for DAG %q", taskID, d.DagID))
	}

	v := reflect.ValueOf(fn)
	if v.Kind() != reflect.Func {
		panic(fmt.Errorf("task fn was a %s, not a func", v.Kind()))
	}

	if err := validateTaskFunc(v.Type()); err != nil {
		panic(fmt.Errorf("error registering task %q for DAG %q: %w", taskID, d.DagID, err))
	}

	fullName := runtime.FuncForPC(v.Pointer()).Name()

	entry := &TaskEntry{
		ID:       taskID,
		Fn:       fn,
		TypeName: extractFuncName(fullName),
		PkgPath:  extractPkgPath(fullName),
	}
	d.tasks = append(d.tasks, entry)
	d.taskMap[taskID] = entry
	return d
}

// SetDownstream declares that fromTaskID has toTaskID as a downstream dependency.
func (d *DagDef) SetDownstream(fromTaskID, toTaskID string) *DagDef {
	d.downstream[fromTaskID] = append(d.downstream[fromTaskID], toTaskID)
	return d
}

// Tasks returns the ordered list of task entries.
func (d *DagDef) Tasks() []*TaskEntry {
	return d.tasks
}

// GetTask finds a task entry by ID within this DAG.
func (d *DagDef) GetTask(taskID string) (*TaskEntry, bool) {
	entry, ok := d.taskMap[taskID]
	return entry, ok
}

// Downstream returns the downstream task IDs for a given task.
func (d *DagDef) Downstream(taskID string) []string {
	return d.downstream[taskID]
}

// Bundle holds a collection of DAGs for coordinator execution.
type Bundle struct {
	Name     string
	Version  string
	Dags     map[string]*DagDef
	DagOrder []string // maintains insertion order
}

// NewBundle creates a new bundle with the given name and version.
func NewBundle(name, version string) *Bundle {
	return &Bundle{
		Name:    name,
		Version: version,
		Dags:    make(map[string]*DagDef),
	}
}

// AddDag creates and registers a new DAG definition.
func (b *Bundle) AddDag(dagID string) *DagDef {
	if _, exists := b.Dags[dagID]; exists {
		panic(fmt.Errorf("DAG %q already exists in bundle", dagID))
	}
	dag := NewDagDef(dagID)
	b.Dags[dagID] = dag
	b.DagOrder = append(b.DagOrder, dagID)
	return dag
}

// GetDag returns a DAG definition by ID.
func (b *Bundle) GetDag(dagID string) (*DagDef, bool) {
	d, ok := b.Dags[dagID]
	return d, ok
}

// OrderedDags returns all DAG definitions in insertion order.
func (b *Bundle) OrderedDags() []*DagDef {
	result := make([]*DagDef, 0, len(b.DagOrder))
	for _, id := range b.DagOrder {
		result = append(result, b.Dags[id])
	}
	return result
}

// --- Helpers ---

// validateTaskFunc performs basic validation of a task function signature.
// The full validation (parameter type injection) is done by bundlev1.NewTaskFunction
// at execution time.
func validateTaskFunc(fnType reflect.Type) error {
	if fnType.NumOut() < 1 || fnType.NumOut() > 2 {
		return fmt.Errorf(
			"task function has %d return values, must be `(result, error)` or just `error`",
			fnType.NumOut(),
		)
	}

	errType := reflect.TypeFor[error]()
	if !fnType.Out(fnType.NumOut() - 1).Implements(errType) {
		return fmt.Errorf(
			"last return value must implement error, got %v",
			fnType.Out(fnType.NumOut()-1),
		)
	}
	return nil
}

// extractFuncName extracts the function name from a fully qualified Go function name.
// E.g., "main.extract" -> "extract", "github.com/user/repo/pkg.MyFunc" -> "MyFunc"
func extractFuncName(fullName string) string {
	parts := strings.Split(fullName, ".")
	name := parts[len(parts)-1]
	return strings.TrimSuffix(name, "-fm")
}

// extractPkgPath extracts the package path from a fully qualified Go function name.
// E.g., "main.extract" -> "main", "github.com/user/repo/pkg.MyFunc" -> "github.com/user/repo/pkg"
func extractPkgPath(fullName string) string {
	lastDot := strings.LastIndex(fullName, ".")
	if lastDot < 0 {
		return ""
	}
	return fullName[:lastDot]
}
