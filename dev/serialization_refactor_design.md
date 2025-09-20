# Serialization Refactoring Design

## Goals
1. Easy to understand code structure
2. Prepare for future split: serialization methods go to Task SDK, deserialization stays in server
3. Retain backward compatibility (SerializedBaseOperator, SerializedDAG, BaseSerialization)
4. Decouple logic for Operator, DAG, and generic serialization

## Current Architecture Problems

### 1. **Mixed Responsibilities**
- `BaseSerialization` contains operator-specific logic (weight_rule, operator_name)
- `serialize_to_json()` in BaseSerialization knows about DAG/Operator specifics
- Single massive `serialize()` method handles all types (880+ lines)

### 2. **Tight Coupling**
- SerializedBaseOperator inherits from both DAGNode and BaseSerialization
- SerializedDAG also inherits from BaseSerialization
- Circular dependencies between classes

### 3. **Complex Flow**
- Multiple layers: serialize() -> serialize_operator() -> _serialize_node() -> serialize_to_json()
- Unclear separation between what happens where

## Proposed Architecture

### 1. **Separate Serializers**
Create dedicated serializer classes for each domain:

```python
# Base serializer - handles primitives and common types
class BaseSerializer:
    """Handles serialization of primitive types and basic objects"""
    def serialize(self, var: Any, *, strict: bool = False) -> Any:
        """Main entry point - routes to appropriate method"""
        
    def serialize_primitive(self, var: Any) -> Any
    def serialize_datetime(self, dt: datetime) -> dict
    def serialize_timedelta(self, td: timedelta) -> dict
    def serialize_timezone(self, tz: Timezone) -> dict
    def serialize_set(self, s: set) -> dict
    def serialize_tuple(self, t: tuple) -> dict
    def serialize_dict(self, d: dict) -> dict
    def serialize_list(self, lst: list) -> list
    # ... other basic types

# Operator serializer - handles operator-specific logic
class OperatorSerializer:
    """Handles serialization of operators and their specific fields"""
    def __init__(self, base_serializer: BaseSerializer):
        self.base = base_serializer
    
    def serialize_operator(self, op: BaseOperator) -> dict:
        """Serialize a BaseOperator"""
        
    def serialize_mapped_operator(self, op: MappedOperator) -> dict:
        """Serialize a MappedOperator"""
        
    def serialize_operator_fields(self, op: BaseOperator, decorated_fields: set) -> dict:
        """Serialize operator fields (replaces serialize_to_json logic)"""
        
    def _is_excluded(self, var: Any, attrname: str, op: BaseOperator) -> bool:
        """Check if field should be excluded from serialization"""
    
# DAG serializer - handles DAG-specific logic  
class DAGSerializer:
    """Handles serialization of DAGs"""
    def __init__(self, base_serializer: BaseSerializer, operator_serializer: OperatorSerializer):
        self.base = base_serializer
        self.operator_serializer = operator_serializer
        
    def serialize_dag(self, dag: DAG) -> dict:
        """Serialize a DAG with all its tasks"""
        
    def serialize_dag_fields(self, dag: DAG, decorated_fields: set) -> dict:
        """Serialize DAG fields (replaces serialize_to_json logic)"""
        
    def _is_excluded(self, var: Any, attrname: str, dag: DAG) -> bool:
        """Check if field should be excluded from serialization"""
```

### 2. **Separate Deserializers**
Mirror structure for deserialization:

```python
class BaseDeserializer:
    """Handles deserialization of primitive types and basic objects"""
    def deserialize(self, data: Any) -> Any:
        """Main entry point - routes to appropriate method"""
        
    def deserialize_primitive(self, data: Any) -> Any
    def deserialize_datetime(self, data: dict) -> datetime
    def deserialize_timedelta(self, data: dict) -> timedelta
    def deserialize_timezone(self, data: str | int) -> Timezone
    def deserialize_set(self, data: list) -> set
    def deserialize_tuple(self, data: list) -> tuple
    def deserialize_dict(self, data: dict) -> dict
    # ... other basic types

class OperatorDeserializer:
    """Handles deserialization of operators"""
    def __init__(self, base_deserializer: BaseDeserializer):
        self.base = base_deserializer
        self._load_operator_extra_links = True
        
    def deserialize_operator(self, data: dict, client_defaults: dict | None = None) -> SerializedBaseOperator:
        """Deserialize operator data into SerializedBaseOperator"""
        
    def populate_operator_fields(self, op: SerializedBaseOperator, data: dict, client_defaults: dict | None = None) -> None:
        """Populate operator fields from serialized data"""
        
    def _preprocess_encoded_operator(self, encoded_op: dict) -> dict:
        """Handle backward compatibility field transformations"""

class DAGDeserializer:
    """Handles deserialization of DAGs"""
    def __init__(self, base_deserializer: BaseDeserializer, operator_deserializer: OperatorDeserializer):
        self.base = base_deserializer
        self.operator_deserializer = operator_deserializer
        
    def deserialize_dag(self, data: dict, client_defaults: dict | None = None) -> SerializedDAG:
        """Deserialize DAG data into SerializedDAG"""
        
    def populate_dag_fields(self, dag: SerializedDAG, data: dict) -> None:
        """Populate DAG fields from serialized data"""
        
    def handle_version_conversion(self, data: dict) -> dict:
        """Handle version conversions (v1->v2, v2->v3)"""
```

### 3. **Backward Compatibility Layer**
Keep existing classes but delegate to new architecture:

```python
class BaseSerialization:
    """Legacy interface - delegates to new serializers/deserializers"""
    # Class variables remain
    _base_serializer = BaseSerializer()
    _base_deserializer = BaseDeserializer()
    
    @classmethod
    def serialize(cls, var: Any, *, strict: bool = False) -> Any:
        # Delegate to appropriate serializer based on type
        if isinstance(var, BaseOperator):
            return OperatorSerializer(cls._base_serializer).serialize_operator(var)
        elif isinstance(var, DAG):
            return DAGSerializer(cls._base_serializer, ...).serialize_dag(var)
        else:
            return cls._base_serializer.serialize(var, strict=strict)
    
    @classmethod
    def deserialize(cls, encoded_var: Any) -> Any:
        # Delegate to appropriate deserializer
        ...

class SerializedBaseOperator(DAGNode, BaseSerialization):
    """Keep existing interface but use new serializers internally"""
    
    @classmethod
    def serialize_operator(cls, op: BaseOperator) -> dict:
        serializer = OperatorSerializer(BaseSerializer())
        return serializer.serialize_operator(op)
    
    @classmethod
    def deserialize_operator(cls, data: dict) -> SerializedBaseOperator:
        deserializer = OperatorDeserializer(BaseDeserializer())
        return deserializer.deserialize_operator(data)

class SerializedDAG(BaseSerialization):
    """Keep existing interface but use new serializers internally"""
    
    @classmethod
    def serialize_dag(cls, dag: DAG) -> dict:
        base_serializer = BaseSerializer()
        op_serializer = OperatorSerializer(base_serializer)
        dag_serializer = DAGSerializer(base_serializer, op_serializer)
        return dag_serializer.serialize_dag(dag)
    
    @classmethod
    def deserialize_dag(cls, data: dict) -> SerializedDAG:
        base_deserializer = BaseDeserializer()
        op_deserializer = OperatorDeserializer(base_deserializer)
        dag_deserializer = DAGDeserializer(base_deserializer, op_deserializer)
        return dag_deserializer.deserialize_dag(data)
```

## Benefits

1. **Clear Separation of Concerns**
   - Each serializer handles only its domain
   - No operator-specific logic in base classes
   - Easy to understand what each class does

2. **Future SDK Split Ready**
   - Serializers can move to SDK
   - Deserializers stay in server
   - Clean interface between them

3. **Maintainable**
   - Smaller, focused classes
   - Clear dependencies
   - Easy to test individual components

4. **Backward Compatible**
   - Existing classes remain
   - Same public API
   - Internal refactoring only

## Implementation Steps

### Phase 1: Create Base Infrastructure
1. Create BaseSerializer class with primitive type handling
2. Create BaseDeserializer class with primitive type handling
3. Move encoding/decoding logic from BaseSerialization

### Phase 2: Create Domain Serializers
1. Create OperatorSerializer with operator-specific logic
2. Create DAGSerializer with DAG-specific logic
3. Extract field serialization logic from serialize_to_json

### Phase 3: Create Domain Deserializers  
1. Create OperatorDeserializer with operator-specific logic
2. Create DAGDeserializer with DAG-specific logic
3. Extract field deserialization logic

### Phase 4: Wire Up Legacy Classes
1. Update BaseSerialization to delegate to new classes
2. Update SerializedBaseOperator methods to use new serializers
3. Update SerializedDAG methods to use new serializers

### Phase 5: Test and Validate
1. Run all tests in airflow-core/tests/unit/serialization
2. Fix any issues
3. Ensure backward compatibility

## Key Design Decisions

1. **Composition over Inheritance**: New classes use composition to share functionality
2. **Single Responsibility**: Each class has one clear purpose
3. **Dependency Injection**: Serializers receive dependencies via constructor
4. **Immutable Serializers**: Serializer classes are stateless for thread safety
5. **Type Safety**: Strong typing throughout for better IDE support and fewer bugs

## Important Considerations

### 1. **Encoding Format**
- Keep the same encoding format (TYPE/VAR structure) for backward compatibility
- Don't change the serialized output format
- Only refactor the internal structure

### 2. **Schema Validation**
- Maintain JSON schema validation functionality
- Keep the same validation logic but move to appropriate classes

### 3. **Client Defaults**
- Preserve client_defaults optimization logic
- Move to appropriate serializer classes

### 4. **Version Handling**
- Keep SERIALIZER_VERSION = 3
- Maintain version conversion functions (conversion_v1_to_v2, conversion_v2_to_v3)

### 5. **Special Cases to Handle**
- Template fields serialization
- Operator extra links
- Params and ParamsDict
- Expand input references
- Task groups
- Asset conditions

### 6. **Class Location Strategy**
```
airflow/serialization/
├── serialized_objects.py        # Keep existing classes for backward compatibility
├── serializers/
│   ├── __init__.py
│   ├── base.py                  # BaseSerializer
│   ├── operator.py              # OperatorSerializer
│   └── dag.py                   # DAGSerializer
└── deserializers/
    ├── __init__.py
    ├── base.py                  # BaseDeserializer
    ├── operator.py              # OperatorDeserializer
    └── dag.py                   # DAGDeserializer
```

### 7. **Special Type Handling**
Move type-specific serialization out of the main serialize() method:

```python
# In BaseSerializer
def serialize(self, var: Any, *, strict: bool = False) -> Any:
    """Route to appropriate serialization method based on type"""
    # Primitives
    if self._is_primitive(var):
        return self.serialize_primitive(var)
    
    # Collections
    elif isinstance(var, dict):
        return self.serialize_dict(var, strict=strict)
    elif isinstance(var, list):
        return self.serialize_list(var, strict=strict)
    elif isinstance(var, set):
        return self.serialize_set(var, strict=strict)
    elif isinstance(var, tuple):
        return self.serialize_tuple(var, strict=strict)
    
    # Date/Time types
    elif isinstance(var, datetime):
        return self.serialize_datetime(var)
    elif isinstance(var, timedelta):
        return self.serialize_timedelta(var)
    elif isinstance(var, Timezone):
        return self.serialize_timezone(var)
    
    # Airflow specific types (these stay in BaseSerialization for now)
    elif isinstance(var, (Param, XComArg, TaskGroup, BaseAsset, etc)):
        return BaseSerialization.serialize(var, strict=strict)
    
    # Unknown type
    else:
        return self.default_serialization(var, strict=strict)
```
