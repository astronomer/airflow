# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Serializer for DAGs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from airflow.exceptions import SerializationError
from airflow.serialization.enums import Encoding
from airflow.serialization.serializers.base import BaseSerializer
from airflow.serialization.serializers.operator import OperatorSerializer

if TYPE_CHECKING:
    from airflow.sdk import DAG


class DAGSerializer:
    """Handles serialization of DAGs."""
    
    def __init__(self, base_serializer: BaseSerializer, operator_serializer: OperatorSerializer):
        self.base = base_serializer
        self.operator_serializer = operator_serializer
        self._decorated_fields: set[str] = {"default_args", "access_control"}
    
    def serialize_dag(self, dag: DAG) -> dict[str, Any]:
        """Serialize a DAG with all its tasks."""
        # Import locally to avoid circular import
        from airflow.serialization.serialized_objects import (
            BaseSerialization, 
            SerializedBaseOperator,
            DAGS_FOLDER
        )
        
        try:
            serialized_dag = self.serialize_dag_fields(dag, self._decorated_fields)
            serialized_dag["_processor_dags_folder"] = DAGS_FOLDER
            serialized_dag["tasks"] = [BaseSerialization.serialize(task) for _, task in dag.task_dict.items()]
            
            from airflow.serialization.serialized_objects import DependencyDetector
            
            dag_deps = [
                dep
                for task in dag.task_dict.values()
                for dep in SerializedBaseOperator.detect_dependencies(task)
            ]
            dag_deps.extend(DependencyDetector.detect_dag_dependencies(dag))
            serialized_dag["dag_dependencies"] = [x.__dict__ for x in sorted(dag_deps)]
            
            from airflow.serialization.serialized_objects import TaskGroupSerialization
            serialized_dag["task_group"] = TaskGroupSerialization.serialize_task_group(dag.task_group)
            
            serialized_dag["deadline"] = (
                [deadline.serialize_deadline_alert() for deadline in dag.deadline]
                if isinstance(dag.deadline, list)
                else None
            )
            
            # Edge info in the JSON exactly matches our internal structure
            serialized_dag["edge_info"] = dag.edge_info
            serialized_dag["params"] = BaseSerialization._serialize_params_dict(dag.params)
            
            # has_on_*_callback are only stored if the value is True, as the default is False
            if dag.has_on_success_callback:
                serialized_dag["has_on_success_callback"] = True
            if dag.has_on_failure_callback:
                serialized_dag["has_on_failure_callback"] = True
            return serialized_dag
        except SerializationError:
            raise
        except Exception as e:
            raise SerializationError(f"Failed to serialize DAG {dag.dag_id!r}: {e}")
    
    def serialize_dag_fields(self, dag: DAG, decorated_fields: set) -> dict[str, Any]:
        """Serialize DAG fields (replaces serialize_to_json logic)."""
        from airflow.serialization.serialized_objects import BaseSerialization, encode_timetable
        
        serialized_object: dict[str, Any] = {}
        keys_to_serialize = dag.get_serialized_fields()
        for key in keys_to_serialize:
            # None is ignored in serialized form and is added back in deserialization.
            value = getattr(dag, key, None)
            if self._is_excluded(value, key, dag):
                continue
            
            if key in decorated_fields:
                serialized_object[key] = BaseSerialization.serialize(value)
            elif key == "timetable" and value is not None:
                serialized_object[key] = encode_timetable(value)
            else:
                value = BaseSerialization.serialize(value)
                if isinstance(value, dict) and Encoding.TYPE in value:
                    value = value[Encoding.VAR]
                serialized_object[key] = value
        return serialized_object
    
    def _is_excluded(self, var: Any, attrname: str, dag: DAG) -> bool:
        """Check if field should be excluded from serialization."""
        # Avoid circular imports
        from airflow.serialization.serialized_objects import SerializedDAG
        return SerializedDAG._is_excluded(var, attrname, dag)
