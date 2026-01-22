# Airflow Memory Optimization Analysis

## Implementation Status Summary

| Issue | Description | Status | Files Modified |
|-------|-------------|--------|----------------|
| 1 | DagRun.task_instances Eager Loading (API) | ✅ FIXED | `dagrun.py`, `dag_runs.py` |
| 2 | Scheduler Running DagRuns Query | ✅ FIXED | `dagrun.py` |
| 3 | Scheduler Task Instance Loop | ✅ FIXED | `scheduler_job_runner.py` |
| 4 | CLI Task List Command | ✅ PARTIALLY FIXED | `task_command.py` |
| 5 | AssetDagRunQueue Unbounded Load | ✅ FIXED | `dag.py` |
| 6 | XCom Clear One-by-One Deletion | ✅ FIXED | `xcom.py` |
| 7 | DagBag Iteration Over SerializedDags | ⚠️ PARTIAL ISSUE | N/A (streaming already used) |
| 8 | Trigger Collection Without Limit | ✅ FALSE POSITIVE | N/A (already optimized) |

### Verification Status

**Completed:**
- ✅ Static code analysis confirmed patterns existed
- ✅ Unit tests pass (no functional regressions)

**Still Needed:**
- [ ] Memory profiling with `tracemalloc` before/after fixes
- [ ] Load testing with large datasets (1000+ TIs, 100+ DAGs)
- [ ] SQL query count verification with logging

---

## Background

This document catalogs query patterns in Apache Airflow that can lead to excessive memory consumption and potential Out-of-Memory (OOM) errors. These issues typically manifest in environments with:

- Many DAGs (100+)
- DAGs with many tasks (50+ tasks per DAG)
- High task instance counts (thousands of historical runs)
- Heavy use of mapped/dynamic tasks
- Large XCom values or many XCom entries
- Extensive use of assets (datasets)

### Root Cause Pattern

The primary anti-pattern is **eager loading of large collections** where:
1. A query uses `joinedload()` or `selectinload()` to fetch related records
2. The related collection can grow unbounded (e.g., task_instances, task_instances_histories)
3. The loaded data is only used for simple checks (existence, count) or iteration

### How Memory Issues Manifest

1. **DAG Processor**: Slow parsing, high memory during serialization
2. **Scheduler**: Memory spikes during scheduling loops
3. **API Server**: Slow responses, OOM on list endpoints
4. **CLI Commands**: Hanging or crashing on large datasets

---

## Critical Issues to Investigate

### 1. DagRun.task_instances Eager Loading

**Location**: `airflow-core/src/airflow/api_fastapi/common/db/dag_runs.py`

```python
def eager_load_dag_run_for_validation() -> tuple[LoaderOption, ...]:
    return (
        joinedload(DagRun.dag_model),
        selectinload(DagRun.task_instances)           # PROBLEM: Loads ALL TIs
            .joinedload(TaskInstance.dag_version)
            .joinedload(DagVersion.bundle),
        selectinload(DagRun.task_instances_histories) # PROBLEM: Loads ALL TI histories
            .joinedload(TaskInstanceHistory.dag_version)
            .joinedload(DagVersion.bundle),
        joinedload(DagRun.dag_run_note),
    )
```

**Why It's a Problem**:
- Called by GET `/dags/{dag_id}/dagRuns` and bulk DAG run endpoints
- Loads ALL task instances AND all task instance histories for EVERY DagRun returned
- A single DAG with 100 tasks and 1000 runs = 100,000 TI records loaded

**Used By**:
- `airflow-core/src/airflow/api_fastapi/core_api/routes/public/dag_run.py:385`
- `airflow-core/src/airflow/api_fastapi/core_api/routes/public/dag_run.py:625`

**What to Verify**:
- [x] Check if task_instances/task_instances_histories are actually needed in the response
- [x] If needed, consider lazy loading or separate endpoints
- [ ] Add pagination for task instances within a DagRun response

**Status**: ✅ **FIXED** - The `dag_versions` property in DagRun now queries dag_version_ids directly when TIs aren't loaded, and the eager loading was removed from `eager_load_dag_run_for_validation()`.

**Fix Applied** (see `airflow-core/src/airflow/models/dagrun.py:393-456` and `airflow-core/src/airflow/api_fastapi/common/db/dag_runs.py`):
- Modified `dag_versions` property to check if TIs are loaded, and if not, query dag_version_ids directly
- Removed TI eager loading from API's `eager_load_dag_run_for_validation()`

**Verification Needed**:
- [ ] Memory profiling before/after with tracemalloc
- [ ] Load testing with DAGs having 100+ tasks and 1000+ runs

---

### 2. Scheduler Running DagRuns Query

**Location**: `airflow-core/src/airflow/models/dagrun.py:598-617`

```python
@classmethod
def get_running_dag_runs_to_examine(cls, session: Session) -> ScalarResult[DagRun]:
    query = (
        select(cls)
        .where(cls.state == DagRunState.RUNNING)
        # ... other filters ...
        .options(joinedload(cls.task_instances))  # PROBLEM: Loads ALL TIs
        .order_by(...)
        .limit(cls.DEFAULT_DAGRUNS_TO_EXAMINE)
    )
```

**Why It's a Problem**:
- Called every scheduler loop iteration
- Loads ALL task instances for each running DagRun
- With 50 concurrent running DAGs × 100 tasks = 5,000 TI objects per loop

**What to Verify**:
- [x] Determine if all task instances are actually needed
- [x] Check if only specific states (e.g., SCHEDULED, RUNNING) are required
- [x] Verify if this can use a filtered subquery instead

**Status**: ✅ **FIXED** - The joinedload was completely unnecessary and has been removed.

**Fix Applied** (see `airflow-core/src/airflow/models/dagrun.py:605-606`):
- Removed `joinedload(cls.task_instances)` from `get_running_dag_runs_to_examine()`
- Task instances are fetched separately with proper state filtering in `task_instance_scheduling_decisions()`

**Verification Needed**:
- [ ] Memory profiling before/after with tracemalloc
- [ ] Load testing with 50+ concurrent running DAGs

---

### 3. Scheduler Task Instance Loop

**Location**: `airflow-core/src/airflow/jobs/scheduler_job_runner.py:2279`

```python
# Select all TIs in State.unfinished and update the dag_version_id
for ti in dag_run.task_instances:  # PROBLEM: Lazy loads ALL TIs
    if ti.state in State.unfinished:
        ti.dag_version = latest_dag_version
```

**Why It's a Problem**:
- Accesses `dag_run.task_instances` relationship which lazy-loads ALL task instances
- Only needs unfinished tasks but loads everything

**What to Verify**:
- [x] Check if `dag_run.task_instances` was already eager-loaded upstream
- [x] If not, this triggers a lazy load of potentially thousands of TIs

**Status**: ✅ **FIXED** - Converted to bulk UPDATE statement.

**Fix Applied** (see `airflow-core/src/airflow/jobs/scheduler_job_runner.py:2278-2287`):
```python
# Bulk update dag_version_id for unfinished TIs instead of loading all TIs and filtering
session.execute(
    update(TI)
    .where(
        TI.dag_id == dag_run.dag_id,
        TI.run_id == dag_run.run_id,
        TI.state.in_(State.unfinished),
    )
    .values(dag_version_id=latest_dag_version.id)
)
```

**Verification Needed**:
- [ ] Memory profiling before/after with tracemalloc
- [ ] Load testing with DAGs having 100+ tasks

---

### 4. CLI Task List Command

**Location**: `airflow-core/src/airflow/cli/commands/task_command.py:361,376`

```python
has_mapped_instances = any(ti.map_index >= 0 for ti in dag_run.task_instances)
# ...
AirflowConsole().print_as(data=dag_run.task_instances, output=args.output, mapper=format_task_instance)
```

**Why It's a Problem**:
- Loads ALL task instances just to check if any are mapped
- Then loads them again (or uses cached) to print

**What to Verify**:
- [x] For the boolean check, use EXISTS subquery instead
- [ ] For printing, consider pagination or streaming

**Status**: ✅ **PARTIALLY FIXED** - EXISTS query implemented for boolean check.

**Fix Applied** (see `airflow-core/src/airflow/cli/commands/task_command.py:361-371`):
```python
# Use EXISTS query instead of loading all task instances just for a boolean check
from sqlalchemy import exists, select

has_mapped_instances = session.scalar(
    select(
        exists()
        .where(TaskInstance.dag_id == dag_run.dag_id)
        .where(TaskInstance.run_id == dag_run.run_id)
        .where(TaskInstance.map_index >= 0)
    )
)
```

**Still TODO**:
- [ ] Add pagination for printing large task instance lists

---

### 5. AssetDagRunQueue Unbounded Load

**Location**: `airflow-core/src/airflow/models/dag.py:631-633`

```python
# this loads all the ADRQ records.... may need to limit num dags  # <-- DEV ACKNOWLEDGES ISSUE
adrq_by_dag: dict[str, list[AssetDagRunQueue]] = defaultdict(list)
for adrq in session.scalars(select(AssetDagRunQueue).options(joinedload(AssetDagRunQueue.dag_model))):
    # ...
```

**Why It's a Problem**:
- The code comment explicitly acknowledges this is problematic
- Loads ALL AssetDagRunQueue records into memory
- No LIMIT, no pagination, no batching

**What to Verify**:
- [x] Determine maximum expected ADRQ count
- [x] Check if this can be processed in batches
- [ ] Consider if streaming is possible

**Status**: ✅ **FIXED** - Bulk delete stale records and filter at query level.

**Fix Applied** (see `airflow-core/src/airflow/models/dag.py:631-647`):
```python
# First, bulk delete stale ADRQs where the associated dag no longer depends on assets.
from sqlalchemy import delete

stale_dag_ids_subq = select(cls.dag_id).where(cls.asset_expression.is_(None)).scalar_subquery()
session.execute(
    delete(AssetDagRunQueue).where(AssetDagRunQueue.target_dag_id.in_(stale_dag_ids_subq))
)

# Now load only valid ADRQs (those that reference dags with asset expressions)
adrq_by_dag: dict[str, list[AssetDagRunQueue]] = defaultdict(list)
for adrq in session.scalars(
    select(AssetDagRunQueue)
    .join(cls, AssetDagRunQueue.target_dag_id == cls.dag_id)
    .where(cls.asset_expression.isnot(None))
):
    adrq_by_dag[adrq.target_dag_id].append(adrq)
```

**Verification Needed**:
- [ ] Memory profiling before/after with tracemalloc
- [ ] Load testing with many asset-triggered DAGs

---

### 6. XCom Clear - One-by-One Deletion

**Location**: `airflow-core/src/airflow/models/xcom.py:150-154`

```python
for xcom in session.scalars(query):
    session.delete(xcom)
session.commit()
```

**Why It's a Problem**:
- Loads all matching XCom records into memory
- Deletes one-by-one (N delete statements)
- For tasks with large XCom output or many keys, this is slow and memory-intensive

**What to Verify**:
- [x] Check if bulk delete is safe here
- [x] Verify if any hooks/events need to fire on delete

**Status**: ✅ **FIXED** - Converted to bulk DELETE.

**Fix Applied** (see `airflow-core/src/airflow/models/xcom.py:146-152`):
```python
# Use bulk delete for efficiency instead of loading and deleting one by one
delete_stmt = delete(cls).where(cls.dag_id == dag_id, cls.task_id == task_id, cls.run_id == run_id)
if map_index is not None:
    delete_stmt = delete_stmt.where(cls.map_index == map_index)

session.execute(delete_stmt)
session.commit()
```

**Verification Needed**:
- [ ] Memory profiling before/after with tracemalloc
- [ ] Load testing with tasks having many XCom entries

---

### 7. DagBag Iteration Over All SerializedDags

**Location**: `airflow-core/src/airflow/models/dagbag.py:90-94`

```python
for sdm in session.scalars(select(SerializedDagModel)):
    if dag := self._read_dag(sdm):
        yield dag
```

**Why It's a Problem**:
- Iterates over ALL serialized DAGs in the database
- While `yield` helps, the query cursor stays open
- Each `_read_dag()` deserializes potentially large JSON

**What to Verify**:
- [x] Check if this is called frequently
- [x] Determine if pagination would help
- [x] Consider if caching reduces the frequency

**Status**: ⚠️ **PARTIAL ISSUE** - Already uses `yield` (streaming), which is good.

**Analysis**:
- The real issue is call frequency from FAB provider's permission sync on every web request
- Caching at the caller level (FAB security manager) would be more effective than pagination
- The generator pattern already helps with memory

**Recommendation**: Add caching/memoization at the FAB caller level rather than modifying the iterator.

---

### 8. Trigger Collection Without Limit

**Location**: `airflow-core/src/airflow/models/trigger.py:337-339`

```python
return list(session.scalars(query).all())
```

**Why It's a Problem**:
- `get_sorted_triggers()` returns ALL triggers matching criteria
- Heavy deferrable operator usage means many triggers
- All loaded into memory as a list

**What to Verify**:
- [x] Check typical trigger counts in production
- [x] Determine if pagination is feasible for caller

**Status**: ✅ **FALSE POSITIVE** - Already well-optimized.

**Analysis**:
- `get_sorted_triggers()` already has capacity limiting built in (line 432: `remaining_capacity = capacity - len(result)`)
- Maximum triggers per loop is configurable (`max_trigger_to_select_per_loop`)
- Returns only IDs (lightweight), not full Trigger objects
- No fix needed

---

## Patterns to Search For

When investigating memory issues, search for these patterns:

### High Priority Patterns

```bash
# Eager loading of task_instances
rg "joinedload.*task_instances|selectinload.*task_instances" --type py

# Relationship access that may lazy-load large collections
rg "\.task_instances\b" --type py -C 3

# .all() calls that could return large datasets
rg "\.all\(\)" --type py -C 2

# Missing LIMIT on selects
rg "session\.scalars\(select\(" --type py -C 5 | grep -v "\.limit("
```

### Medium Priority Patterns

```bash
# for loops over session.scalars (potential unbounded iteration)
rg "for .+ in session\.scalars\(" --type py -C 3

# joinedload in general (review each for large collections)
rg "joinedload\(" --type py

# selectinload in general
rg "selectinload\(" --type py
```

---

## Testing & Verification

### Memory Profiling

```python
# Add memory tracking to suspicious functions
import tracemalloc

tracemalloc.start()
# ... run the suspicious code ...
current, peak = tracemalloc.get_traced_memory()
print(f"Current: {current / 1024 / 1024:.1f} MB, Peak: {peak / 1024 / 1024:.1f} MB")
tracemalloc.stop()
```

### Query Analysis

```python
# Enable SQL logging to see actual queries
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.DEBUG)
```

### Load Testing Scenarios

1. **Many TaskInstances**: Create a DAG with 1000+ historical runs, each with 50+ tasks
2. **Large Mapped Tasks**: Create tasks that map to 1000+ instances
3. **Many Concurrent Runs**: Run 100+ DAGs simultaneously
4. **Asset-Heavy DAGs**: Create many DAGs with asset dependencies

---

## Fixed Issues (Reference)

### SerializedDagModel.write_dag - joinedload for boolean check

**Location**: `airflow-core/src/airflow/models/serialized_dag.py`

**Original Code**:
```python
dag_version = session.scalar(
    select(DagVersion)
    .where(DagVersion.dag_id == dag.dag_id)
    .options(joinedload(DagVersion.task_instances))  # Loaded ALL TIs!
    .order_by(DagVersion.created_at.desc())
    .limit(1)
)
# ...
if dag_version and not dag_version.task_instances:  # Only used for boolean check!
```

**Fixed Code**:
```python
dag_version = session.scalar(
    select(DagVersion)
    .where(DagVersion.dag_id == dag.dag_id)
    .order_by(DagVersion.created_at.desc())
    .limit(1)
)

# Efficient EXISTS check
has_task_instances = dag_version and session.scalar(
    exists().where(TaskInstance.dag_version_id == dag_version.id).select()
)

if dag_version and not has_task_instances:
```

**Lesson**: Never use `joinedload()` just to check if a collection is empty. Use `EXISTS` instead.

---

## Checklist for Code Review

When reviewing code that touches the database, verify:

- [ ] **No unbounded `.all()` calls** on potentially large tables (TaskInstance, XCom, Log, etc.)
- [ ] **LIMIT clauses** on queries that could return many rows
- [ ] **Pagination** for API endpoints returning collections
- [ ] **EXISTS subqueries** instead of loading collections for boolean checks
- [ ] **Targeted queries** instead of relationship access for filtered data
- [ ] **Batch processing** for operations on many records
- [ ] **Streaming/generators** for iteration over large datasets
- [ ] **No eager loading of large collections** unless absolutely necessary

---

## Related Tables to Watch

These tables can grow very large and queries against them need extra care:

| Table | Growth Factor | Risk Level |
|-------|--------------|------------|
| `task_instance` | tasks × runs | Critical |
| `task_instance_history` | tasks × runs × retries | Critical |
| `xcom` | tasks × runs × keys | High |
| `rendered_task_instance_fields` | tasks × runs | High |
| `log` | tasks × runs × events | High |
| `dag_run` | runs per DAG | Medium |
| `trigger` | deferred tasks | Medium |
| `asset_event` | asset updates | Medium |

---

## Resources

- [SQLAlchemy Loading Relationships](https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html)
- [SQLAlchemy Performance](https://docs.sqlalchemy.org/en/20/faq/performance.html)
- [Airflow Architecture](.cursor/rules/airflow-architecture.mdc)
