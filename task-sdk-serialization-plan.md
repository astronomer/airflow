<!--
 Licensed to the Apache Software Foundation (ASF) under one
 or more contributor license agreements.  See the NOTICE file
 distributed with this work for additional information
 regarding copyright ownership.  The ASF licenses this file
 to you under the Apache License, Version 2.0 (the
 "License"); you may not use this file except in compliance
 with the License.  You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing,
 software distributed under the License is distributed on an
 "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 KIND, either express or implied.  See the License for the
 specific language governing permissions and limitations
 under the License.
 -->

# Task SDK Serialization/Deserialization Strict Versioning Plan

## Table of Contents
1. [Current State Analysis](#1-current-state-analysis)
2. [Problem Statement](#2-problem-statement)
3. [Proposed Solutions](#3-proposed-solutions)
4. [Implementation Plan](#4-implementation-plan)
5. [Migration Strategy](#5-migration-strategy)
6. [Alternative Considerations](#6-alternative-considerations)
7. [Success Criteria](#7-success-criteria)
8. [Risks and Mitigations](#8-risks-and-mitigations)
9. [Recommendation](#9-recommendation)

## Related Context
- **GitHub Issue**: [#45428](https://github.com/apache/airflow/issues/45428)
- **Goal**: Make serialization and deserialization stricter with versioning for Task SDK separation
- **Target Version**: Airflow 3.1

## 1. Current State Analysis

### Current Architecture
The current serialization system in Airflow 2.x was designed to minimize the size of serialized DAGs stored in the database while maintaining all information needed for the Scheduler and Webserver.

#### Key Components

##### 1.1 Serialization Logic (`airflow/serialization/serialized_objects.py`)
- **Optimization Strategy**: Excludes default values and None values to reduce JSON size
- **Key Methods**:
  ```python
  def _is_excluded(cls, var: Any, attrname: str, instance: Any) -> bool:
      """Check if type is excluded from serialization."""
      if var is None:
          if not cls._is_constructor_param(attrname, instance):
              # Any instance attribute, that is not a constructor argument, we exclude None as the default
              return True
          return cls._value_is_hardcoded_default(attrname, var, instance)
      return isinstance(var, cls._excluded_types) or cls._value_is_hardcoded_default(
          attrname, var, instance
      )
  ```

##### 1.2 Default Value Detection
- **`_value_is_hardcoded_default()`**: Uses identity comparison (`is`) to detect defaults
- **`_CONSTRUCTOR_PARAMS`**: Stores BaseOperator constructor parameter defaults
- **`OPERATOR_DEFAULTS`**: Dictionary with ~23 default operator values from Task SDK

##### 1.3 Current Schema (`airflow/serialization/schema.json`)
- Defines structure and types but not default values
- Minimal required fields:
  - DAG: `dag_id`, `fileloc`, `tasks`
  - Operator: `task_type`, `_task_module`, `task_id`, `ui_color`, `ui_fgcolor`, `template_fields`

##### 1.4 Inheritance Dependency
- `SerializedBaseOperator` inherits from `BaseOperator`
- `SerializedDAG` inherits from `DAG`
- Deserialization relies on parent class defaults being available

### Current Data Flow
```
DAG Definition → DAG Processor → Serialization (excludes defaults) → Database
                                                ↓
Webserver/Scheduler ← Deserialization (adds defaults from inheritance) ← Database
```

### Example of Current Behavior
Given an operator with defaults:
```python
task = EmptyOperator(
    task_id="example",
    # pool="default_pool" - excluded because it matches default
    # retries=0 - excluded because it matches default
    # depends_on_past=False - excluded
)
```

Serialized JSON only contains:
```json
{
  "task_id": "example",
  "task_type": "EmptyOperator",
  "_task_module": "airflow.operators.empty",
  "ui_color": "#e8f7e4",
  "ui_fgcolor": "#000",
  "template_fields": []
}
```

## 2. Problem Statement

### Architectural Change in Airflow 3.1
With the Task SDK separation:
- **Client (Task SDK)**: Language-specific, handles serialization (DAG → JSON)
- **Server (airflow-core)**: Language-agnostic, handles deserialization (JSON → SerializedDAG)
- **Breaking Change**: Server will NOT have access to SDK's BaseOperator class

### Current Issues
1. **Inheritance Dependency**: Deserialization requires BaseOperator/DAG class defaults
2. **Implicit Knowledge**: Server needs to "know" what defaults should be
3. **Version Mismatch Risk**: Different SDK versions might have different defaults
4. **Language Support**: Non-Python SDKs won't have the same class hierarchy

### Requirements for New System
1. **Self-Contained JSON**: All information needed for deserialization must be in the JSON
2. **Version Compatibility**: Support multiple SDK versions simultaneously
3. **Language Agnostic**: Work with Python, Go, and future SDK languages
4. **Schema Contract**: Clear, versioned schema as the contract between client and server

## 3. Proposed Solutions

### Key Difference Between Options
- **Option 1**: Include ALL fields in JSON, even if they match defaults
- **Option 2**: OMIT fields that match defaults, use schema to fill them in
- **Option 3**: Include a separate defaults section in JSON, reference it for common values

**Quick Example** - Task with all default values:
- **Option 1 JSON**: `{"task_id": "t1", "pool": "default_pool", "retries": 0, "pool_slots": 1, ...}` (all fields present)
- **Option 2 JSON**: `{"task_id": "t1"}` (only non-default fields, schema provides the rest)
- **Option 3 JSON**: `{"client_defaults": {"BaseOperator": {"pool": "default_pool", "retries": 0, ...}}, "tasks": [{"task_id": "t1"}]}`

### Size Impact Analysis

**Example DAG with 1000 similar tasks**:
```
Assumptions:
- Each task has ~25 fields
- 20 fields typically use default values
- Average field size: 20 bytes (including JSON structure)

Option 1 (Full Serialization):
- Per task: 25 fields × 20 bytes = 500 bytes
- Total: 1000 tasks × 500 bytes = 500 KB
- Network transfer: 500 KB per API call

Option 2 (Schema-based):
- Per task: 5 non-default fields × 20 bytes = 100 bytes
- Total: 1000 tasks × 100 bytes = 100 KB
- Network transfer: 100 KB per API call
- Savings: 80% reduction

Option 3 (Hierarchical Client Defaults):
- Client defaults section: ~2 KB (includes BaseOperator, DAG, and specific operator defaults)
- Per task: 5 unique fields × 20 bytes = 100 bytes
- Total: 2 KB + (1000 × 100 bytes) = 102 KB
- Savings: ~80% reduction with self-contained defaults
- Benefit: Supports SDK-specific defaults and inheritance

Option 3 + Optional Field Omission:
- Client defaults section: ~2 KB
- Per task: 3-4 unique non-empty fields × 20 bytes = 60-80 bytes
- Total: 2 KB + (1000 × 70 bytes avg) = 72 KB
- Savings: ~85% reduction (5-10% additional savings)
- Benefit: Maximizes efficiency while remaining self-contained
```

### Option 1: Full Serialization
Remove all default exclusion logic and serialize every attribute, regardless of whether it matches the default value or not.

**Implementation**:
```python
@classmethod
def _is_excluded(cls, var: Any, attrname: str, instance: Any) -> bool:
    # Only exclude truly non-serializable types
    return isinstance(var, cls._excluded_types)
```

**Pros**:
- ✅ Simplest implementation
- ✅ Most resilient to version mismatches
- ✅ Completely self-contained JSON (no external schema needed)
- ✅ No coordination needed between client/server versions
- ✅ Clear debugging - what you see is what you get
- ✅ Default changes don't affect existing serialized DAGs

**Cons**:
- ❌ Larger JSON size (estimated 2-3x increase)
- ❌ More network bandwidth for API calls
- ❌ More storage space in database
- ❌ Massive redundancy (same defaults repeated across all tasks)
- ❌ In a DAG with 1000 tasks, stores the same 20+ default values 1000 times

**Example Output**:
```json
{
  "task_id": "example",
  "task_type": "EmptyOperator",
  "_task_module": "airflow.operators.empty",
  "ui_color": "#e8f7e4",
  "ui_fgcolor": "#000",
  "template_fields": [],
  "depends_on_past": false,
  "pool": "default_pool",
  "pool_slots": 1,
  "retries": 0,
  "retry_delay": 300,
  "priority_weight": 1,
  "weight_rule": "downstream",
  "queue": "default",
  "owner": "airflow",
  "trigger_rule": "all_success",
  // ... all other fields with their values
}
```

### Option 2: Schema-Based Defaults (Recommended)
Define all defaults in the JSON schema using JSON Schema's `default` keyword.

**Version Awareness Clarification**: All options require some version awareness, but this option requires tracking TWO separate version systems:
1. Serialization format version (v1, v2, etc.)
2. Schema definition version (to know which schema to apply)

The key point: Each schema version contains its own defaults within the schema definition itself. The complexity comes from needing to:
- Store which schema version was current when the DAG was serialized
- Apply the correct schema (with its embedded defaults) during deserialization

This is more complex than Option 1 where defaults are explicitly included in the JSON.

**What the Server Stores**:
```
schemas/
├── v2.0.0/
│   └── schema.json  (contains "pool_slots": {"default": 1})
├── v2.1.0/
│   └── schema.json  (contains "pool_slots": {"default": 2})
└── v2.2.0/
    └── schema.json  (contains new defaults)
```

The server doesn't store defaults separately - they're part of each schema version. The "history" is just having multiple schema files available.

**Schema Example**:
```json
{
  "properties": {
    "pool": { 
      "type": "string", 
      "default": "default_pool" 
    },
    "pool_slots": { 
      "type": "number", 
      "default": 1 
    },
    "depends_on_past": { 
      "type": "boolean", 
      "default": false 
    }
  }
}
```

**Pros**:
- ✅ Dramatically smaller JSON size (70-80% reduction possible)
- ✅ Single source of truth for defaults (in schema)
- ✅ Standard JSON Schema feature
- ✅ Eliminates massive redundancy in database
- ✅ Much better network efficiency for API calls
- ✅ Follows DRY principle - defaults stored once, not per task
- ✅ Schema versioning is a solved problem (see GraphQL, OpenAPI, Protocol Buffers)

**Cons**:
- ❌ Schema must be updated when defaults change
- ❌ Version coordination challenges  
- ❌ Complex migration when defaults change
- ❌ Server needs to maintain multiple schema file versions (e.g., schema_v2.0.0.json, schema_v2.1.0.json)

### Option 3: Hierarchical Client Defaults (Hybrid Approach)
Include a hierarchical defaults section that respects inheritance and allows SDK-specific defaults.

**Structure**:
```json
{
  "__version": 2,
  "__schema_version": "2.1.0",
  "client_defaults": {
    "BaseOperator": {
      "retries": 3,              // SDK-specific: Go SDK uses 3 retries by default
      "pool": "default_pool",
      "owner": "airflow-go",     // SDK-specific: Go SDK default owner
      "priority_weight": 1
    },
    "DAG": {
      "max_active_tasks": 16,
      "max_active_runs": 16,
      "catchup": true
    },
    "BashOperator": {
      "bash_command": "/bin/true",  // Safer default for Go SDK
      "env": {"PATH": "/usr/bin"}   // Go-specific environment
    }
  },
  "dag": {
    "tasks": [
      {
        "task_id": "task1",
        "task_type": "BashOperator",
        // Only values different from client_defaults are included
        "bash_command": "echo hello"  // Overrides default "/bin/true"
        // Inherits: retries=3, owner="airflow-go", env={"PATH": "/usr/bin"}
      }
    ]
  }
}
```

**Application Logic**:
```python
def apply_defaults_by_type(obj_data: dict, obj_type: str, client_defaults: dict, schema: dict):
    """Apply defaults based on object type and inheritance hierarchy."""
    
    # 1. Start with schema defaults (server-side universals)
    schema_props = schema.get("definitions", {}).get(obj_type, {}).get("properties", {})
    for field, definition in schema_props.items():
        if field not in obj_data and "default" in definition:
            obj_data[field] = definition["default"]
    
    # 2. Apply BaseOperator defaults for all operators
    if obj_type != "BaseOperator" and is_operator_type(obj_type):
        base_defaults = client_defaults.get("BaseOperator", {})
        for field, value in base_defaults.items():
            if field not in obj_data:
                obj_data[field] = value
    
    # 3. Apply specific type defaults
    type_defaults = client_defaults.get(obj_type, {})
    for field, value in type_defaults.items():
        if field not in obj_data:
            obj_data[field] = value
    
    return obj_data
```

**Real-World Multi-SDK Example**:

Python SDK DAG:
```json
{
  "__version": 2,
  "client_defaults": {
    "BaseOperator": {
      "retries": 0,              // Python default
      "owner": "airflow",        // Python default
      "pool": "default_pool"
    },
    "BashOperator": {
      "bash_command": "",
      "env": null
    }
  },
  "dag": { /* tasks */ }
}
```

Go SDK DAG (same DAG, different defaults):
```json
{
  "__version": 2,
  "client_defaults": {
    "BaseOperator": {
      "retries": 3,              // Go SDK prefers retries
      "owner": "airflow-go",     // Go-specific owner
      "pool": "default_pool",
      "timeout": 300             // Go SDK adds timeout by default
    },
    "BashOperator": {
      "bash_command": "/bin/true",
      "env": {"PATH": "/usr/bin:/bin"},  // Go needs explicit PATH
      "shell": "/bin/bash"               // Go specifies shell
    }
  },
  "dag": { /* same tasks */ }
}
```

The server correctly interprets both DAGs despite different SDK conventions.

**Pros**:
- ✅ Balance between size and flexibility (70-80% size reduction like Option 2)
- ✅ Self-contained - no external schema files needed
- ✅ SDK-specific defaults supported (Go vs Python vs Java)
- ✅ Natural inheritance model (BaseOperator → specific operators)
- ✅ Version-specific defaults included in the JSON
- ✅ Easy to debug - defaults are visible in the JSON
- ✅ Follows DRY principle while remaining readable
- ✅ Can be combined with optional field omission for extra savings

**Cons**:
- ❌ More complex than Option 1 (but simpler than Option 2)
- ❌ Slightly larger than Option 2 (includes defaults in JSON)
- ❌ Need to implement inheritance logic for defaults
- ❌ SDK must know its own default hierarchy

### Version Management Comparison

| Aspect | Option 1 (Full) | Option 2 (Schema) | Option 3 (Hierarchical) |
|--------|-----------------|-------------------|------------------------|
| Version Types | Serialization only | Serialization + Schema | Serialization only |
| SDK-Specific Defaults | No | No | Yes |
| Self-Contained JSON | Yes | No (needs schema files) | Yes |
| Default Changes | New serialization version | Update schema version | Update client_defaults |
| Backward Compatibility | Read old format | Apply correct schema version | Read old format |
| Implementation Complexity | Low | Medium | Medium |
| Storage Efficiency | Poor (2-3x larger) | Excellent (70-80% smaller) | Excellent (70-85% smaller) |
| Network Efficiency | Poor | Excellent | Excellent |
| Inheritance Support | N/A | Schema-based | Natural class hierarchy |
| Debugging | Easy (all visible) | Hard (need schema) | Easy (defaults visible) |

**Example Scenario**: If `pool_slots` default changes from 1 to 2:
- **Option 1**: Always serializes ALL fields. Both old and new DAGs have `"pool_slots": 1` or `"pool_slots": 2` explicitly in JSON
- **Option 2**: Fields matching defaults are OMITTED from JSON. Schema provides the default:
  - Old DAG + schema v2.0.0: No `pool_slots` in JSON → schema supplies default of 1
  - New DAG + schema v2.1.0: No `pool_slots` in JSON → schema supplies default of 2
  - Custom value: `"pool_slots": 5` in JSON → overrides schema default
- **Option 3**: Update client_defaults section. Old DAGs keep their defaults, new DAGs get new defaults:
  - Old DAG: `"client_defaults": {"BaseOperator": {"pool_slots": 1}}`
  - New DAG: `"client_defaults": {"BaseOperator": {"pool_slots": 2}}`
  - Tasks inherit from client_defaults unless explicitly overridden
  - **Key Benefit**: Each DAG is self-documenting about what defaults were in effect when it was created

## 4. Implementation Plan

### Phase 1: Version Bump and Infrastructure (Week 1)
1. **Update Version**:
   ```python
   SERIALIZER_VERSION = 2  # was 1
   ```

2. **Add Version Handling**:
   ```python
   @classmethod
   def from_dict(cls, serialized_obj: dict) -> SerializedDAG:
       ver = serialized_obj.get("__version", "<not present>")
       if ver not in (1, 2):
           raise ValueError(f"Unsure how to deserialize version {ver!r}")
       if ver == 1:
           cls.conversion_v1_to_v2(serialized_obj)
       return cls.deserialize_dag(serialized_obj["dag"])
   ```

3. **Create Feature Flag**:
   ```python
   FULL_SERIALIZATION_ENABLED = conf.getboolean(
       "core", "enable_full_serialization", fallback=False
   )
   ```

### Phase 2: Implement Option 3 Serialization (Week 2-3)

#### 2.1 Update Exclusion Logic for Client Defaults + Optional Field Omission
```python
@classmethod
def _is_excluded(cls, var: Any, attrname: str, instance: Any, client_defaults: dict = None) -> bool:
    """Check if field should be excluded from serialization."""
    if cls.SERIALIZER_VERSION >= 2:
        # 1. Check if it's an optional field with null/empty value
        if cls._is_optional_empty_field(attrname, var, instance):
            return True
        
        # 2. Check if value matches client defaults
        if client_defaults:
            obj_type = type(instance).__name__
            
            # Check BaseOperator defaults for all operators
            if obj_type != "BaseOperator" and cls._is_operator_type(obj_type):
                base_default = client_defaults.get("BaseOperator", {}).get(attrname)
                if base_default is not None and var == base_default:
                    return True
            
            # Check specific type defaults
            type_default = client_defaults.get(obj_type, {}).get(attrname)
            if type_default is not None and var == type_default:
                return True
        
        # 3. Still exclude non-serializable types
        return isinstance(var, cls._excluded_types)
    
    # Legacy behavior for version 1
    if var is None:
        if not cls._is_constructor_param(attrname, instance):
            return True
        return cls._value_is_hardcoded_default(attrname, var, instance)
    return isinstance(var, cls._excluded_types) or cls._value_is_hardcoded_default(
        attrname, var, instance
    )

@classmethod
def _is_optional_empty_field(cls, attrname: str, value: Any, instance: Any) -> bool:
    """Check if field is optional in schema and has empty/null value."""
    # Get schema for object type
    obj_type = type(instance).__name__.lower()
    if obj_type == "dag":
        obj_type = "dag"
    elif obj_type.endswith("operator"):
        obj_type = "operator"
    
    schema_def = cls._get_schema_definition(obj_type)
    required_fields = schema_def.get("required", [])
    
    # Never exclude required fields
    if attrname in required_fields:
        return False
    
    # Exclude if null or empty
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    
    return False
```

#### 2.2 Update Schema with Defaults
```json
{
  "properties": {
    "task_id": {
      "type": "string",
      "description": "Unique task identifier"
    },
    "pool": {
      "type": "string",
      "default": "default_pool"
    },
    "pool_slots": {
      "type": "integer",
      "default": 1
    },
    "retries": {
      "type": "integer", 
      "default": 0
    },
    "retry_delay": {
      "type": "integer",
      "default": 300,
      "description": "Seconds between retries"
    },
    "priority_weight": {
      "type": "integer",
      "default": 1
    },
    "depends_on_past": {
      "type": "boolean",
      "default": false
    },
    "trigger_rule": {
      "type": "string",
      "default": "all_success"
    }
    // ... all other fields with their defaults
  }
}

#### 2.3 Update Deserialization with Schema Defaults
```python
@classmethod
def populate_operator(cls, op: SchedulerOperator, encoded_op: dict[str, Any], schema_version: str) -> None:
    """Populate operator attributes with serialized values and schema defaults."""
    if cls.SERIALIZER_VERSION >= 2:
        # Get schema for this version
        schema = schema_registry.get_schema(schema_version)
        operator_schema = schema["properties"]
        
        # First, apply all schema defaults
        for field_name, field_def in operator_schema.items():
            if "default" in field_def and field_name not in encoded_op:
                setattr(op, field_name, field_def["default"])
        
        # Then, overlay the values from JSON
        for k, v in encoded_op.items():
            setattr(op, k, cls.deserialize(v))
    else:
        # Legacy v1 behavior
        # ... existing code ...
```

### Phase 3: Testing and Validation (Week 4)

#### 3.1 Unit Tests
```python
def test_v2_serialization_includes_all_defaults():
    """Test that v2 serialization includes all default values."""
    op = EmptyOperator(task_id="test")
    serialized = SerializedBaseOperator.serialize_operator(op)
    
    # Check that all defaults are present
    assert serialized["pool"] == "default_pool"
    assert serialized["pool_slots"] == 1
    assert serialized["depends_on_past"] is False
    # ... check all defaults
```

#### 3.2 Size Impact Testing
```python
def test_serialization_size_impact():
    """Measure the size increase from v1 to v2."""
    dag = create_test_dag_with_100_tasks()
    
    v1_size = len(json.dumps(serialize_dag_v1(dag)))
    v2_size = len(json.dumps(serialize_dag_v2(dag)))
    
    size_increase = v2_size / v1_size
    assert size_increase < 3.0  # Less than 3x increase
```

#### 3.3 Performance Testing
- Measure serialization time for large DAGs
- Measure deserialization time
- Test database query performance with larger JSON

#### 3.4 Detailed Performance Benchmarks

##### Test DAG Suite
```python
# performance_test_dags.py
def create_benchmark_dags():
    """Create standardized DAGs for performance testing."""
    return {
        "small": create_linear_dag(task_count=10),
        "medium": create_complex_dag(task_count=100, parallel_chains=5),
        "large": create_complex_dag(task_count=1000, parallel_chains=20),
        "provider_heavy": create_provider_dag(providers=["aws", "gcp", "databricks"]),
        "dynamic": create_dynamic_dag(mapped_tasks=50),
        "deep_nested": create_nested_task_groups(depth=5, tasks_per_group=10)
    }
```

##### Performance Metrics
```python
@pytest.mark.benchmark
def test_serialization_performance_suite():
    """Comprehensive performance benchmark suite."""
    results = {}
    
    for dag_type, dag in create_benchmark_dags().items():
        # Measure serialization
        start_time = time.monotonic()
        serialized = SerializedDAG.serialize_dag(dag)
        serialization_time = time.monotonic() - start_time
        
        # Measure size
        json_str = json.dumps(serialized)
        compressed_size = len(zlib.compress(json_str.encode()))
        
        # Measure deserialization
        start_time = time.monotonic()
        SerializedDAG.deserialize_dag(serialized)
        deserialization_time = time.monotonic() - start_time
        
        results[dag_type] = {
            "task_count": len(dag.tasks),
            "serialization_time_ms": serialization_time * 1000,
            "deserialization_time_ms": deserialization_time * 1000,
            "json_size_kb": len(json_str) / 1024,
            "compressed_size_kb": compressed_size / 1024,
            "time_per_task_ms": (serialization_time * 1000) / len(dag.tasks)
        }
    
    # Assert performance thresholds
    assert results["small"]["time_per_task_ms"] < 5  # < 5ms per task
    assert results["large"]["serialization_time_ms"] < 5000  # < 5s total
    assert results["large"]["json_size_kb"] / results["large"]["task_count"] < 10  # < 10KB per task
```

##### Database Performance Testing
```python
def test_database_performance():
    """Test database operations with larger serialized DAGs."""
    large_dag = create_complex_dag(task_count=1000)
    serialized = SerializedDAG.serialize_dag(large_dag)
    
    # Test write performance
    start_time = time.monotonic()
    SerializedDagModel.write_dag(large_dag)
    write_time = time.monotonic() - start_time
    
    # Test read performance
    start_time = time.monotonic()
    SerializedDagModel.get_dag(large_dag.dag_id)
    read_time = time.monotonic() - start_time
    
    # Test query performance with multiple DAGs
    with create_session() as session:
        start_time = time.monotonic()
        session.query(SerializedDagModel).filter(
            SerializedDagModel.dag_id.in_([f"dag_{i}" for i in range(100)])
        ).all()
        query_time = time.monotonic() - start_time
    
    assert write_time < 1.0  # < 1 second
    assert read_time < 0.5   # < 500ms
    assert query_time < 2.0  # < 2 seconds for 100 DAGs
```

### Phase 4: Migration Tools (Week 5)

#### 4.1 Migration Command
```python
@cli_utils.action_cli
def migrate_serialized_dags(args):
    """Migrate existing serialized DAGs from v1 to v2."""
    with create_session() as session:
        dags = session.query(SerializedDagModel).all()
        for dag_model in dags:
            if dag_model.data.get("__version") == 1:
                v2_data = convert_v1_to_v2(dag_model.data)
                dag_model.data = v2_data
        session.commit()
```

#### 4.2 Rollback Capability
```python
@cli_utils.action_cli
def rollback_serialized_dags(args):
    """Rollback serialized DAGs from v2 to v1 if needed."""
    with create_session() as session:
        dags = session.query(SerializedDagModel).filter(
            SerializedDagModel.data["__version"].astext == "2"
        ).all()
        
        rollback_count = 0
        failed_dags = []
        
        for dag_model in dags:
            try:
                v1_data = convert_v2_to_v1(dag_model.data)
                dag_model.data = v1_data
                rollback_count += 1
            except Exception as e:
                failed_dags.append((dag_model.dag_id, str(e)))
        
        session.commit()
        
        print(f"Rolled back {rollback_count} DAGs")
        if failed_dags:
            print(f"Failed to rollback {len(failed_dags)} DAGs:")
            for dag_id, error in failed_dags:
                print(f"  - {dag_id}: {error}")
```

## 5. Migration Strategy

### 5.1 Detailed Migration Plan

#### Pre-Migration Phase (Week -1)
1. **Validation and Analysis**:
   ```python
   def pre_migration_validation():
       """Validate all DAGs can be serialized in v2 format."""
       report = {
           "total_dags": 0,
           "v2_compatible": 0,
           "needs_attention": [],
           "size_analysis": {}
       }
       
       for dag in get_all_dags():
           try:
               v1_data = SerializedDAG.serialize_dag_v1(dag)
               v2_data = SerializedDAG.serialize_dag_v2(dag)
               
               size_increase = len(json.dumps(v2_data)) / len(json.dumps(v1_data))
               report["size_analysis"][dag.dag_id] = size_increase
               
               if size_increase > 5.0:  # Flag DAGs with >5x increase
                   report["needs_attention"].append({
                       "dag_id": dag.dag_id,
                       "reason": f"Large size increase: {size_increase:.1f}x"
                   })
               
               report["v2_compatible"] += 1
           except Exception as e:
               report["needs_attention"].append({
                   "dag_id": dag.dag_id,
                   "reason": str(e)
               })
           
           report["total_dags"] += 1
       
       return report
   ```

2. **Generate Migration Report**:
   - List of DAGs requiring manual review
   - Expected storage impact
   - Performance impact estimates

#### Phased Rollout (Weeks 1-4)
1. **Phase 1 - Canary (Week 1)**:
   - Enable for 1% of DAGs
   - Monitor metrics for 72 hours
   - Automatic rollback if error rate > 0.1%

2. **Phase 2 - Limited (Week 2)**:
   - Increase to 10% of DAGs
   - A/B test performance impact
   - Gather user feedback

3. **Phase 3 - Broad (Week 3)**:
   - Expand to 50% of DAGs
   - Full monitoring dashboard active
   - Support team briefed

4. **Phase 4 - General (Week 4)**:
   - Enable for all DAGs
   - Keep rollback ready
   - 24/7 monitoring

#### Rollback Procedures
1. **Immediate Rollback** (< 5 minutes):
   ```bash
   # Disable v2 serialization globally
   airflow config set core enable_full_serialization false
   
   # Restart dag processors
   systemctl restart airflow-dag-processor
   ```

2. **Data Rollback** (< 30 minutes):
   ```bash
   # Rollback all v2 DAGs to v1
   airflow dags rollback-serialization --all
   
   # Verify rollback
   airflow dags verify-serialization --version 1
   ```

3. **Emergency Procedures**:
   - Hotfix to force v1 deserialization
   - Database query to revert DAGs
   - Bypass serialization temporarily

### 5.2 Backward Compatibility Timeline
- **3.1.0**: v2 introduced, v1 fully supported
- **3.2.0**: v2 default for new deployments
- **3.3.0**: v2 default for all deployments
- **4.0.0**: v1 deprecated with warnings
- **5.0.0**: v1 support removed

### 5.3 Communication Plan
1. **6 Weeks Before Release**:
   - Blog post announcing changes
   - Dev list discussion thread
   - Documentation preview

2. **2 Weeks Before Release**:
   - Migration guide published
   - Webinar for users
   - Support team training

3. **Release Week**:
   - Release notes with examples
   - Slack/Discord announcements
   - Office hours for questions

4. **Post-Release**:
   - Weekly status updates
   - Performance reports
   - Success stories

## 6. Alternative Considerations

### 6.1 Compression
If size becomes critical:
```python
@property
def data(self) -> dict | None:
    if self._data_compressed:
        return json.loads(zlib.decompress(self._data_compressed))
    return self._data
```

### 6.2 Selective Defaults
Only serialize non-primitive defaults:
```python
def should_include_default(value):
    # Include complex defaults, exclude simple ones
    return isinstance(value, (dict, list, object)) and value not in [[], {}]
```

### 6.3 Reference Deduplication
For DAGs with many similar operators:
```json
{
  "operators": {
    "op1": { /* full definition */ },
    "op2": { "ref": "op1", "overrides": { "task_id": "different" } }
  }
}
```

## 7. Schema Evolution Strategy

### 7.1 Schema Versioning

#### Independent Schema Version
```json
{
  "__version": 2,  // Serialization format version
  "__schema_version": "2.0.0",  // Schema definition version
  "dag": { ... }
}
```

#### Version Compatibility Matrix
| Serialization Version | Schema Versions | Notes |
|----------------------|-----------------|-------|
| v1 | 1.0.0 - 1.x.x | Legacy format |
| v2 | 2.0.0 - 2.x.x | Full serialization |
| v3 (future) | 3.0.0+ | Next major change |

### 7.2 Field Management Guidelines

#### Adding New Fields
```python
class SchemaEvolution:
    """Guidelines for adding new fields to serialized format."""
    
    @staticmethod
    def add_field(field_name: str, field_type: str, default_value: Any):
        """Add new field to schema."""
        rules = {
            "required": False,  # New fields must be optional
            "default": default_value,  # Must have sensible default
            "deprecated_after": None,  # Not deprecated initially
            "added_in_version": "2.1.0",  # Track when added
        }
        
        # Update schema.json
        schema_update = {
            field_name: {
                "type": field_type,
                "default": default_value,
                "description": f"Added in schema version {rules['added_in_version']}"
            }
        }
        
        return schema_update
```

#### Deprecating Fields
```python
def deprecate_field(field_name: str, removal_version: str):
    """Mark field for deprecation."""
    return {
        field_name: {
            "deprecated": True,
            "deprecation_version": "2.2.0",
            "removal_version": removal_version,
            "migration_path": f"Use 'new_{field_name}' instead"
        }
    }
```

### 7.3 Schema Migration Examples

#### Example: Adding Execution Context Field
```python
# Version 2.1.0 - Add execution context
{
    "properties": {
        "execution_context": {
            "type": "object",
            "default": {},
            "description": "Runtime execution context (added in 2.1.0)",
            "properties": {
                "cluster": {"type": "string"},
                "namespace": {"type": "string"},
                "labels": {"type": "object"}
            }
        }
    }
}

# Backward compatibility handler
def handle_missing_execution_context(task_dict):
    """Add default execution_context for older versions."""
    if "execution_context" not in task_dict:
        task_dict["execution_context"] = {}
    return task_dict
```

## 8. Cross-Language Compatibility Testing

### 8.1 Language-Agnostic Test Suite

#### Reference JSON Generation
```python
def generate_reference_jsons():
    """Generate canonical JSON files for cross-language testing."""
    test_cases = {
        "minimal_dag": {
            "description": "Simplest possible DAG",
            "dag": create_minimal_dag(),
        },
        "complex_dag": {
            "description": "DAG with all features",
            "dag": create_complex_dag_with_all_features(),
        },
        "provider_dag": {
            "description": "DAG with provider operators",
            "dag": create_provider_heavy_dag(),
        }
    }
    
    for name, case in test_cases.items():
        serialized = SerializedDAG.serialize_dag(case["dag"])
        
        # Save canonical JSON
        with open(f"test/cross_language/{name}.json", "w") as f:
            json.dump(serialized, f, indent=2, sort_keys=True)
        
        # Save human-readable documentation
        with open(f"test/cross_language/{name}.md", "w") as f:
            f.write(f"# {case['description']}\n\n")
            f.write("## Expected Structure\n")
            f.write(generate_structure_docs(serialized))
```

### 8.2 Go SDK Compatibility Test

```go
// test_deserialization.go
package airflow_test

import (
    "encoding/json"
    "testing"
    "github.com/apache/airflow-go-sdk/dag"
)

func TestDeserializeReferenceDAGs(t *testing.T) {
    testCases := []string{
        "minimal_dag.json",
        "complex_dag.json", 
        "provider_dag.json",
    }
    
    for _, testFile := range testCases {
        t.Run(testFile, func(t *testing.T) {
            // Read reference JSON
            data, err := os.ReadFile(filepath.Join("test/cross_language", testFile))
            if err != nil {
                t.Fatalf("Failed to read test file: %v", err)
            }
            
            // Deserialize to Go structures
            var serializedDag dag.SerializedDAG
            err = json.Unmarshal(data, &serializedDag)
            if err != nil {
                t.Fatalf("Failed to deserialize: %v", err)
            }
            
            // Validate structure
            validateDAGStructure(t, serializedDag)
            
            // Re-serialize and compare
            reserializedJSON, err := json.Marshal(serializedDag)
            if err != nil {
                t.Fatalf("Failed to re-serialize: %v", err)
            }
            
            // Compare canonical forms
            assertJSONEqual(t, data, reserializedJSON)
        })
    }
}
```

### 8.3 JavaScript/TypeScript Validation

```typescript
// test/crossLanguageCompatibility.test.ts
import { describe, it, expect } from '@jest/globals';
import { SerializedDAG, deserializeDAG } from '@airflow/sdk-js';
import * as fs from 'fs';
import * as path from 'path';

describe('Cross-Language DAG Deserialization', () => {
  const testFiles = [
    'minimal_dag.json',
    'complex_dag.json',
    'provider_dag.json'
  ];

  testFiles.forEach(testFile => {
    it(`should deserialize ${testFile}`, () => {
      // Read reference JSON
      const jsonPath = path.join(__dirname, 'cross_language', testFile);
      const jsonContent = fs.readFileSync(jsonPath, 'utf-8');
      const serializedData = JSON.parse(jsonContent);
      
      // Deserialize
      const dag = deserializeDAG(serializedData);
      
      // Validate structure
      expect(dag).toBeDefined();
      expect(dag.dagId).toBe(serializedData.dag.dag_id);
      expect(dag.tasks.length).toBe(serializedData.dag.tasks.length);
      
      // Validate task properties
      dag.tasks.forEach((task, index) => {
        const serializedTask = serializedData.dag.tasks[index].__var;
        expect(task.taskId).toBe(serializedTask.task_id);
        expect(task.taskType).toBe(serializedTask.task_type);
        
        // Check all operator defaults are present
        expect(task.pool).toBeDefined();
        expect(task.retries).toBeDefined();
        expect(task.dependsOnPast).toBeDefined();
      });
    });
  });
});
```

### 8.4 Contract Validation Tests

```python
def test_serialization_contract():
    """Ensure serialization output matches documented contract."""
    
    # Load JSON Schema
    with open("airflow/serialization/schema.json") as f:
        schema = json.load(f)
    
    # Create test DAG with all features
    test_dag = create_comprehensive_test_dag()
    
    # Serialize
    serialized = SerializedDAG.serialize_dag(test_dag)
    
    # Validate against schema
    jsonschema.validate(serialized, schema)
    
    # Additional contract validations
    assert "__version" in serialized
    assert serialized["__version"] == 2
    
    # Ensure all expected fields are present
    for task in serialized["dag"]["tasks"]:
        task_var = task["__var"]
        
        # All defaults must be explicitly included
        for field, default_value in OPERATOR_DEFAULTS.items():
            assert field in task_var, f"Missing default field: {field}"
            
            # For v2, values should match expected defaults
            if task_var.get(field) == default_value:
                # Default is explicitly included
                pass
            else:
                # Non-default value preserved
                assert task_var[field] != default_value
```

## 9. Success Criteria

### 9.1 Functional Requirements
- ✅ Server can deserialize without SDK dependencies
- ✅ All operator attributes preserved correctly
- ✅ Support for v1 and v2 formats
- ✅ No data loss during serialization/deserialization

### 9.2 Performance Requirements
- ✅ Serialization size increase < 3x
- ✅ Serialization time increase < 50%
- ✅ Deserialization time increase < 50%
- ✅ No significant database performance impact

### 9.3 Quality Requirements
- ✅ 100% test coverage for new code
- ✅ No regression in existing functionality
- ✅ Clear error messages for validation failures
- ✅ Comprehensive documentation

## 10. Monitoring and Alerting

### 10.1 Key Metrics to Monitor

#### Serialization Metrics
```python
# Prometheus metrics for monitoring
from prometheus_client import Histogram, Counter, Gauge

serialization_duration = Histogram(
    'airflow_serialization_duration_seconds',
    'Time spent serializing DAGs',
    ['dag_id', 'version']
)

serialization_size = Histogram(
    'airflow_serialization_size_bytes',
    'Size of serialized DAGs',
    ['dag_id', 'version'],
    buckets=[1000, 10000, 100000, 1000000, 10000000]  # 1KB to 10MB
)

serialization_errors = Counter(
    'airflow_serialization_errors_total',
    'Total number of serialization errors',
    ['dag_id', 'error_type']
)

serialization_version_usage = Gauge(
    'airflow_serialization_version_usage',
    'Number of DAGs using each serialization version',
    ['version']
)
```

#### Database Impact Metrics
```python
db_serialized_dag_count = Gauge(
    'airflow_db_serialized_dag_count',
    'Total number of serialized DAGs in database'
)

db_serialized_dag_total_size = Gauge(
    'airflow_db_serialized_dag_total_size_mb',
    'Total size of serialized DAGs in database in MB'
)

db_query_duration = Histogram(
    'airflow_db_serialized_dag_query_seconds',
    'Time to query serialized DAGs',
    ['operation']  # read, write, list
)
```

### 10.2 Alerting Rules

```yaml
# prometheus_alerts.yml
groups:
  - name: airflow_serialization
    rules:
      - alert: SerializationErrorRate
        expr: rate(airflow_serialization_errors_total[5m]) > 0.01
        for: 10m
        annotations:
          summary: "High serialization error rate"
          description: "Serialization error rate is {{ $value }} errors/sec"
      
      - alert: SerializationSizeAnomaly
        expr: |
          airflow_serialization_size_bytes{quantile="0.99"} / 
          airflow_serialization_size_bytes{quantile="0.50"} > 10
        for: 15m
        annotations:
          summary: "Unusual DAG serialization size detected"
          description: "99th percentile is 10x larger than median"
      
      - alert: DatabaseSizeGrowth
        expr: rate(airflow_db_serialized_dag_total_size_mb[1h]) > 100
        for: 30m
        annotations:
          summary: "Rapid database growth detected"
          description: "Database growing at {{ $value }} MB/hour"
      
      - alert: SerializationPerformanceDegradation
        expr: |
          histogram_quantile(0.95, 
            rate(airflow_serialization_duration_seconds_bucket[5m])
          ) > 1.0
        for: 10m
        annotations:
          summary: "Slow DAG serialization detected"
          description: "95th percentile serialization time is {{ $value }} seconds"
```

### 10.3 Monitoring Dashboard

#### Grafana Dashboard Configuration
```json
{
  "dashboard": {
    "title": "Airflow Serialization Monitoring",
    "panels": [
      {
        "title": "Serialization Version Distribution",
        "targets": [
          {
            "expr": "airflow_serialization_version_usage"
          }
        ],
        "type": "piechart"
      },
      {
        "title": "Serialization Performance",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(airflow_serialization_duration_seconds_bucket[5m]))",
            "legendFormat": "p95"
          },
          {
            "expr": "histogram_quantile(0.99, rate(airflow_serialization_duration_seconds_bucket[5m]))",
            "legendFormat": "p99"
          }
        ],
        "type": "graph"
      },
      {
        "title": "DAG Size Distribution",
        "targets": [
          {
            "expr": "histogram_quantile(0.5, airflow_serialization_size_bytes)",
            "legendFormat": "median"
          },
          {
            "expr": "histogram_quantile(0.95, airflow_serialization_size_bytes)",
            "legendFormat": "p95"
          }
        ],
        "type": "graph"
      },
      {
        "title": "Error Rate",
        "targets": [
          {
            "expr": "rate(airflow_serialization_errors_total[5m])"
          }
        ],
        "type": "graph"
      }
    ]
  }
}
```

### 10.4 Health Check Endpoints

```python
@router.get("/health/serialization")
async def serialization_health_check(session: Session = Depends(get_session)):
    """Health check endpoint for serialization system."""
    
    health_status = {
        "status": "healthy",
        "checks": {},
        "metrics": {}
    }
    
    # Check v2 serialization is working
    try:
        test_dag = create_minimal_test_dag()
        serialized = SerializedDAG.serialize_dag(test_dag)
        SerializedDAG.deserialize_dag(serialized)
        health_status["checks"]["v2_serialization"] = "pass"
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["checks"]["v2_serialization"] = f"fail: {str(e)}"
    
    # Check database performance
    start_time = time.monotonic()
    dag_count = session.query(SerializedDagModel).count()
    query_time = time.monotonic() - start_time
    
    health_status["metrics"]["total_dags"] = dag_count
    health_status["metrics"]["query_time_ms"] = query_time * 1000
    
    if query_time > 1.0:  # Slow query threshold
        health_status["status"] = "degraded"
        health_status["checks"]["db_performance"] = "slow"
    
    return health_status
```

## 11. Risks and Mitigations

### 11.1 Risk: Database Storage Impact
- **Impact**: 3x larger serialized DAGs could strain database
- **Mitigation**: 
  - Implement compression
  - Monitor database growth
  - Provide cleanup tools
  - Consider column type optimization

### 11.2 Risk: API Performance
- **Impact**: Larger payloads slow down API calls
- **Mitigation**:
  - Implement pagination
  - Add response compression
  - Cache frequently accessed DAGs

### 11.3 Risk: Breaking Changes
- **Impact**: Existing integrations might break
- **Mitigation**:
  - Extensive testing
  - Beta program
  - Clear migration path
  - Maintain v1 compatibility

### 11.4 Risk: Complex DAGs
- **Impact**: Very large DAGs might hit size limits
- **Mitigation**:
  - Set reasonable limits
  - Provide DAG optimization guide
  - Implement streaming for large DAGs

## 12. Recommendation

**Final Recommendation: Option 3 - Hierarchical Client Defaults**

### Why Option 3 is the Best Compromise

After considering all three options, Option 3 (Hierarchical Client Defaults) emerges as the optimal solution because it combines the best aspects of both approaches:

#### Efficiency Like Option 2
- **~85% size reduction** compared to Option 1 (with optional field omission)
- **Excellent network performance** for API operations
- **Follows DRY principle** - defaults stored once per DAG
- **Additional optimization** - empty optional fields automatically omitted

#### Simplicity Like Option 1
- **Self-contained JSON** - no external schema files needed
- **Easy debugging** - defaults are visible in the JSON
- **Natural inheritance** - matches how developers think about classes

#### Unique Benefits
- **SDK-specific defaults** - Go, Python, Java can have different defaults
- **Language-aware** - Can encode language-specific behaviors
- **Future-proof** - New SDKs can define their own defaults

### Revised Rationale for Option 3
1. **Best of Both Worlds**: Nearly as efficient as Option 2, nearly as simple as Option 1
2. **SDK Flexibility**: Each SDK can optimize defaults for its language/ecosystem
3. **Self-Contained**: No schema registry complexity or version management
4. **Natural Model**: Inheritance hierarchy matches developer expectations
5. **Migration Friendly**: Easy to implement incrementally

### Implementation Strategy for Option 3
1. **SDK Default Generation**:
   ```python
   # Each SDK generates its own defaults
   class GoSDKDefaults:
       @staticmethod
       def get_client_defaults():
           return {
               "BaseOperator": {
                   "retries": 3,  # Go SDK prefers more retries
                   "owner": "airflow-go",
                   "pool": "default_pool"
               },
               "BashOperator": {
                   "bash_command": "/bin/true",
                   "env": {"PATH": "/usr/bin:/bin"}
               }
           }
   ```

2. **Inheritance Resolution**:
   ```python
   def resolve_task_defaults(task_data, task_type, client_defaults):
       # Apply BaseOperator defaults first
       if task_type != "BaseOperator":
           apply_defaults(task_data, client_defaults.get("BaseOperator", {}))
       
       # Then apply specific operator defaults
       apply_defaults(task_data, client_defaults.get(task_type, {}))
       
       return task_data
   ```

3. **Gradual Migration Path**:
   - Phase 1: Implement full serialization (Option 1) for immediate needs
   - Phase 2: Add client_defaults section while maintaining full serialization
   - Phase 3: Start omitting fields that match client_defaults
   - Phase 4: Full Option 3 implementation with inheritance

### When to Use Each Option

**Option 1 (Full Serialization)**:
- Proof of concept or MVP phase
- Teams prioritizing development speed over efficiency
- Small DAGs where size isn't a concern

**Option 2 (Schema-Based)**:
- Existing schema management infrastructure
- Strict size constraints
- Single SDK environment (e.g., Python-only)

**Option 3 (Hierarchical Client Defaults)**:
- Multi-SDK environments (Python, Go, Java)
- Need for SDK-specific optimizations
- Want efficiency without external dependencies
- Teams familiar with inheritance concepts

### Additional Optimization: Optional Field Omission

Beyond the client defaults mechanism, we can further optimize by omitting optional fields with null/empty values:

**Serialization Logic**:
```python
def should_omit_field(field_name: str, value: Any, schema: dict, obj_type: str) -> bool:
    """Determine if a field should be omitted from serialization."""
    # Get the schema definition for this object type
    obj_schema = schema.get("definitions", {}).get(obj_type, {})
    required_fields = obj_schema.get("required", [])
    
    # Never omit required fields
    if field_name in required_fields:
        return False
    
    # Omit optional fields with null/empty values
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    
    return False
```

**Examples of Optional Fields** (from schema.json):
- DAG: `doc_md`, `description`, `owner_links`, `_processor_dags_folder`
- Operator: `doc`, `doc_md`, `doc_json`, `doc_yaml`, `doc_rst`, `label`

**Combined Savings Example**:
```json
// Before (Option 1):
{
  "dag_id": "my_dag",
  "description": "",      // Empty optional field
  "doc_md": null,        // Null optional field
  "owner_links": {},     // Empty optional dict
  "tasks": [{
    "task_id": "task1",
    "doc": "",           // Empty optional field
    "doc_md": null,      // Null optional field
    "pool": "default_pool",  // Default value
    "retries": 0         // Default value
  }]
}

// After (Option 3 + Optional Field Omission):
{
  "client_defaults": {
    "BaseOperator": {
      "pool": "default_pool",
      "retries": 0
    }
  },
  "dag": {
    "dag_id": "my_dag",
    // All empty optional fields omitted
    "tasks": [{
      "task_id": "task1"
      // All empty optional fields and defaults omitted
    }]
  }
}
```

**Additional Size Reduction**: ~5-10% on top of the 70-80% from client defaults

### Key Implementation Considerations

**For Option 3 Success**:

1. **SDK Registration**:
   ```python
   class SDKRegistry:
       """Registry of SDK-specific defaults."""
       
       @classmethod
       def register_sdk(cls, sdk_name: str, version: str, defaults: dict):
           """Register an SDK's default configuration."""
           cls._registry[f"{sdk_name}-{version}"] = defaults
       
       @classmethod
       def get_defaults(cls, sdk_name: str, version: str) -> dict:
           """Retrieve defaults for a specific SDK version."""
           return cls._registry.get(f"{sdk_name}-{version}", {})
   ```

2. **Validation**:
   - Ensure client_defaults match expected operator types
   - Validate inheritance chains are correct
   - Check for conflicting defaults between base and derived classes

3. **Testing Strategy**:
   - Test each SDK's default generation
   - Verify inheritance resolution works correctly
   - Ensure size reduction targets are met
   - Cross-SDK compatibility testing

### Implementation Priority for Option 3
1. Define inheritance hierarchy for all operator types
2. Implement client_defaults generation in each SDK
3. Build defaults resolution logic with proper inheritance
4. Create migration path from v1 to v2 with client_defaults
5. Extensive testing across all SDKs

### Final Note on Tradeoffs

All three approaches have merit:
- **Option 1** prioritizes simplicity but sacrifices efficiency
- **Option 2** maximizes efficiency but requires schema infrastructure
- **Option 3** balances efficiency with self-containment and SDK flexibility

**Why Option 3 Wins**:
1. **Pragmatic Balance**: 85% of Option 2's efficiency with 80% of Option 1's simplicity
2. **SDK Diversity**: Critical for Airflow's multi-language future (Python, Go, Java, Rust)
3. **Self-Contained**: No external dependencies or schema registry needed
4. **Natural Model**: Inheritance hierarchy matches how developers think
5. **Future-Proof**: New SDKs can define their own optimized defaults
6. **Best Practices**: Combines client defaults with optional field omission for maximum efficiency

Given Airflow's trajectory toward multiple SDKs and the need for both efficiency and maintainability, Option 3's hierarchical client defaults provide the best foundation for the future.

### Success Metrics
- Deployment success rate > 99%
- No increase in serialization-related errors
- User feedback positive
- Performance within acceptable bounds

## Appendix A: Current Default Values

### OPERATOR_DEFAULTS from Task SDK
```python
OPERATOR_DEFAULTS: dict[str, Any] = {
    "allow_nested_operators": True,
    "depends_on_past": False,
    "execution_timeout": DEFAULT_TASK_EXECUTION_TIMEOUT,
    "executor_config": {},
    "ignore_first_depends_on_past": DEFAULT_IGNORE_FIRST_DEPENDS_ON_PAST,
    "inlets": [],
    "map_index_template": None,
    "on_execute_callback": [],
    "on_failure_callback": [],
    "on_retry_callback": [],
    "on_skipped_callback": [],
    "on_success_callback": [],
    "outlets": [],
    "owner": DEFAULT_OWNER,
    "pool_slots": DEFAULT_POOL_SLOTS,
    "priority_weight": DEFAULT_PRIORITY_WEIGHT,
    "queue": DEFAULT_QUEUE,
    "retries": DEFAULT_RETRIES,
    "retry_delay": DEFAULT_RETRY_DELAY,
    "retry_exponential_backoff": False,
    "trigger_rule": DEFAULT_TRIGGER_RULE,
    "wait_for_past_depends_before_skipping": DEFAULT_WAIT_FOR_PAST_DEPENDS_BEFORE_SKIPPING,
    "wait_for_downstream": False,
    "weight_rule": DEFAULT_WEIGHT_RULE,
}
```

### Configuration-Based Defaults
- `DEFAULT_OWNER`: from `[operators] default_owner` (default: "airflow")
- `DEFAULT_POOL_SLOTS`: 1
- `DEFAULT_PRIORITY_WEIGHT`: 1
- `DEFAULT_QUEUE`: from `[operators] default_queue` (default: "default")
- `DEFAULT_RETRIES`: from `[core] default_task_retries` (default: 0)
- `DEFAULT_RETRY_DELAY`: from `[core] default_task_retry_delay` (default: 300 seconds)

## Appendix B: Example Serialized DAG Comparison

### Version 1 (Current)
```json
{
  "__version": 1,
  "dag": {
    "dag_id": "example_dag",
    "fileloc": "/opt/airflow/dags/example.py",
    "tasks": [
      {
        "__type": "operator",
        "__var": {
          "task_id": "example_task",
          "task_type": "EmptyOperator",
          "_task_module": "airflow.operators.empty",
          "ui_color": "#e8f7e4",
          "ui_fgcolor": "#000",
          "template_fields": [],
          "downstream_task_ids": []
        }
      }
    ]
  }
}
```

### Version 2 (Proposed)
```json
{
  "__version": 2,
  "dag": {
    "dag_id": "example_dag",
    "fileloc": "/opt/airflow/dags/example.py",
    "tasks": [
      {
        "__type": "operator",
        "__var": {
          "task_id": "example_task",
          "task_type": "EmptyOperator",
          "_task_module": "airflow.operators.empty",
          "ui_color": "#e8f7e4",
          "ui_fgcolor": "#000",
          "template_fields": [],
          "downstream_task_ids": [],
          "allow_nested_operators": true,
          "depends_on_past": false,
          "execution_timeout": null,
          "executor_config": {},
          "ignore_first_depends_on_past": false,
          "inlets": [],
          "map_index_template": null,
          "on_execute_callback": [],
          "on_failure_callback": [],
          "on_retry_callback": [],
          "on_skipped_callback": [],
          "on_success_callback": [],
          "outlets": [],
          "owner": "airflow",
          "pool": "default_pool",
          "pool_slots": 1,
          "priority_weight": 1,
          "queue": "default",
          "retries": 0,
          "retry_delay": 300,
          "retry_exponential_backoff": false,
          "trigger_rule": "all_success",
          "wait_for_past_depends_before_skipping": false,
          "wait_for_downstream": false,
          "weight_rule": "downstream"
        }
      }
    ]
  }
}
```

## Appendix C: Testing Checklist

- [ ] Unit tests for v2 serialization
- [ ] Unit tests for v1 to v2 conversion
- [ ] Integration tests with Task SDK
- [ ] Performance benchmarks
- [ ] Database storage impact analysis
- [ ] API response time testing
- [ ] Memory usage profiling
- [ ] Backward compatibility tests
- [ ] Migration tool testing
- [ ] Documentation review
