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
"""Deserializer for DAGs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from airflow._shared.timezones.timezone import utcnow
from airflow.exceptions import DeserializationError
from airflow.serialization.deserializers.base import BaseDeserializer
from airflow.serialization.deserializers.operator import OperatorDeserializer
from airflow.serialization.enums import DagAttributeTypes as DAT, Encoding
# decode functions and DeadlineAlert are imported later to avoid circular import

if TYPE_CHECKING:
    from airflow.serialization.serialized_objects import SerializedDAG


class DAGDeserializer:
    """Handles deserialization of DAGs."""
    
    def __init__(self, base_deserializer: BaseDeserializer, operator_deserializer: OperatorDeserializer):
        self.base = base_deserializer
        self.operator_deserializer = operator_deserializer
        self._decorated_fields: set[str] = {"default_args", "access_control"}
    
    def deserialize_dag(
        self, 
        data: dict[str, Any], 
        client_defaults: dict[str, Any] | None = None
    ) -> SerializedDAG:
        """Deserialize DAG data into SerializedDAG."""
        from airflow.serialization.serialized_objects import SerializedDAG
        
        if "dag_id" not in data:
            raise DeserializationError(
                message="Encoded dag object has no dag_id key. "
                "You may need to run `airflow dags reserialize`."
            )
        
        dag_id = data["dag_id"]
        
        try:
            return self._deserialize_dag_internal(data, client_defaults)
        except (_TimetableNotRegistered, DeserializationError):
            # Let specific errors bubble up unchanged
            raise
        except Exception as err:
            # Wrap all other errors consistently
            raise DeserializationError(dag_id) from err
    
    def _deserialize_dag_internal(
        self, 
        encoded_dag: dict[str, Any], 
        client_defaults: dict[str, Any] | None = None
    ) -> SerializedDAG:
        """Handle the main Dag deserialization logic."""
        from airflow.serialization.serialized_objects import (
            BaseSerialization,
            SerializedBaseOperator,
            SerializedDAG,
            SerializedTaskGroup,
            TaskGroupSerialization
        )
        
        dag = SerializedDAG(dag_id=encoded_dag["dag_id"])
        dag.last_loaded = utcnow()
        
        # Note: Context is passed explicitly through method parameters, no class attributes needed
        
        for k, v in encoded_dag.items():
            if k == "_downstream_task_ids":
                v = set(v)
            elif k == "tasks":
                SerializedBaseOperator._load_operator_extra_links = self.operator_deserializer._load_operator_extra_links
                tasks = {}
                for obj in v:
                    if obj.get(Encoding.TYPE) == DAT.OP:
                        deser = SerializedBaseOperator.deserialize_operator(
                            obj[Encoding.VAR], client_defaults
                        )
                        tasks[deser.task_id] = deser
                k = "task_dict"
                v = tasks
            elif k == "timezone":
                v = self.base.deserialize_timezone(v)
            elif k == "dagrun_timeout":
                v = self.base.deserialize_timedelta(v)
            elif k.endswith("_date"):
                v = self.base.deserialize_datetime(v)
            elif k == "edge_info":
                # Value structure matches exactly
                pass
            elif k == "timetable":
                from airflow.serialization.serialized_objects import decode_timetable
                v = decode_timetable(v)
            elif k == "weight_rule":
                from airflow.serialization.serialized_objects import decode_priority_weight_strategy
                v = decode_priority_weight_strategy(v)
            elif k in self._decorated_fields:
                v = BaseSerialization.deserialize(v)
            elif k == "params":
                v = BaseSerialization._deserialize_params_dict(v)
            elif k == "tags":
                v = set(v)
            # else use v as it is
            
            object.__setattr__(dag, k, v)
        
        # Set _task_group
        if "task_group" in encoded_dag:
            tg = TaskGroupSerialization.deserialize_task_group(
                encoded_dag["task_group"],
                None,
                dag.task_dict,
                dag,
            )
            object.__setattr__(dag, "task_group", tg)
        else:
            # This must be old data that had no task_group. Create a root
            # task group and add all tasks to it.
            tg = SerializedTaskGroup(
                group_id=None,
                group_display_name=None,
                prefix_group_id=True,
                parent_group=None,
                dag=dag,
                tooltip="",
            )
            object.__setattr__(dag, "task_group", tg)
            for task in dag.tasks:
                tg.add(task)
        
        # Set has_on_*_callbacks to True if they exist in Serialized blob as False is the default
        if "has_on_success_callback" in encoded_dag:
            dag.has_on_success_callback = True
        if "has_on_failure_callback" in encoded_dag:
            dag.has_on_failure_callback = True
        
        if "deadline" in encoded_dag and encoded_dag["deadline"] is not None:
            from airflow.serialization.serialized_objects import DeadlineAlert
            dag.deadline = (
                [
                    DeadlineAlert.deserialize_deadline_alert(deadline_data)
                    for deadline_data in encoded_dag["deadline"]
                ]
                if encoded_dag["deadline"]
                else None
            )
        
        keys_to_set_none = dag.get_serialized_fields() - encoded_dag.keys() - SerializedDAG._CONSTRUCTOR_PARAMS.keys()
        for k in keys_to_set_none:
            setattr(dag, k, None)
        
        for t in dag.task_dict.values():
            SerializedBaseOperator.set_task_dag_references(t, dag)
        
        return dag
    
    def handle_version_conversion(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle version conversions (v1->v2, v2->v3)."""
        from airflow.serialization.serialized_objects import SerializedDAG
        
        ver = data.get("__version", "<not present>")
        if ver not in (1, 2, 3):
            raise ValueError(f"Unsure how to deserialize version {ver!r}")
        if ver == 1:
            SerializedDAG.conversion_v1_to_v2(data)
        if ver == 2:
            SerializedDAG.conversion_v2_to_v3(data)
        
        return data


class _TimetableNotRegistered(ValueError):
    def __init__(self, type_string: str) -> None:
        self.type_string = type_string

    def __str__(self) -> str:
        return (
            f"Timetable class {self.type_string!r} is not registered or "
            "you have a top level database access that disrupted the session. "
            "Please check the airflow best practices documentation."
        )
