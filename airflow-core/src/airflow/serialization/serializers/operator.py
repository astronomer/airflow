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
"""Serializer for operators."""

from __future__ import annotations

from inspect import signature
from textwrap import dedent
from typing import TYPE_CHECKING, Any

from airflow.exceptions import AirflowException
from airflow.serialization.enums import DagAttributeTypes as DAT, Encoding
from airflow.serialization.helpers import serialize_template_field
from airflow.serialization.serializers.base import BaseSerializer
# encode_priority_weight_strategy is imported later to avoid circular import
# encode_timetable and encode_start_trigger_args are imported later to avoid circular import
from airflow.utils.module_loading import qualname

if TYPE_CHECKING:
    from airflow.sdk import BaseOperator
    from airflow.sdk.definitions.mappedoperator import MappedOperator


class OperatorSerializer:
    """Handles serialization of operators and their specific fields."""
    
    def __init__(self, base_serializer: BaseSerializer):
        self.base = base_serializer
        self._decorated_fields = {"executor_config"}
    
    def serialize_operator(self, op: BaseOperator) -> dict[str, Any]:
        """Serialize a BaseOperator."""
        from airflow.sdk import BaseOperator as SdkBaseOperator
        serialize_op = self.serialize_operator_fields(op, self._decorated_fields)
        
        if not op.email:
            # If "email" is empty, we do not need to include other email attrs
            for attr in ["email_on_failure", "email_on_retry"]:
                if attr in serialize_op:
                    del serialize_op[attr]
        
        # Detect if there's a change in python callable name
        python_callable = getattr(op, "python_callable", None)
        if python_callable:
            callable_name = qualname(python_callable)
            serialize_op["python_callable_name"] = callable_name
        
        serialize_op["task_type"] = getattr(op, "task_type", type(op).__name__)
        serialize_op["_task_module"] = getattr(op, "_task_module", type(op).__module__)
        if op.operator_name != serialize_op["task_type"]:
            serialize_op["_operator_name"] = op.operator_name
        
        # Used to determine if an Operator is inherited from EmptyOperator
        if op.inherits_from_empty_operator:
            serialize_op["_is_empty"] = True
        
        # Used to determine if an Operator is inherited from SkipMixin or BranchMixin
        if op.inherits_from_skipmixin:
            serialize_op["_can_skip_downstream"] = True
        
        if op.start_trigger_args:
            from airflow.serialization.serialized_objects import encode_start_trigger_args
            serialize_op["start_trigger_args"] = encode_start_trigger_args(op.start_trigger_args)
        
        if op.operator_extra_links:
            serialize_op["_operator_extra_links"] = self._serialize_operator_extra_links(
                op.operator_extra_links.__get__(op)
                if isinstance(op.operator_extra_links, property)
                else op.operator_extra_links
            )
        
        # Store all template_fields as they are if there are JSON Serializable
        # If not, store them as strings
        # And raise an exception if the field is not templateable
        forbidden_fields = set(signature(SdkBaseOperator.__init__).parameters.keys())
        # Though allow some of the BaseOperator fields to be templated anyway
        forbidden_fields.difference_update({"email"})
        if op.template_fields:
            for template_field in op.template_fields:
                if template_field in forbidden_fields:
                    raise AirflowException(
                        dedent(
                            f"""Cannot template BaseOperator field:
                        {template_field!r} {op.__class__.__name__=} {op.template_fields=}"""
                        )
                    )
                value = getattr(op, template_field, None)
                if not self._is_excluded(value, template_field, op):
                    serialize_op[template_field] = serialize_template_field(value, template_field)
        
        if op.params:
            # Avoid circular imports
            from airflow.serialization.serialized_objects import BaseSerialization
            serialize_op["params"] = BaseSerialization._serialize_params_dict(op.params)
        
        return serialize_op
    
    def serialize_mapped_operator(self, op: MappedOperator) -> dict[str, Any]:
        """Serialize a MappedOperator."""
        from airflow.serialization.serialized_objects import _ExpandInputRef, BaseSerialization
        
        serialized_op = self._serialize_node(op)
        # Handle expand_input and op_kwargs_expand_input.
        expansion_kwargs = op._get_specified_expand_input()
        if TYPE_CHECKING:  # Let Mypy check the input type for us!
            _ExpandInputRef.validate_expand_input_value(expansion_kwargs.value)
        serialized_op[op._expand_input_attr] = {
            "type": type(expansion_kwargs).EXPAND_INPUT_TYPE,
            "value": BaseSerialization.serialize(expansion_kwargs.value),
        }
        
        if op.partial_kwargs:
            serialized_op["partial_kwargs"] = {}
            for k, v in op.partial_kwargs.items():
                if self._is_excluded(v, k, op):
                    continue
                
                if k in [f"on_{x}_callback" for x in ("execute", "failure", "success", "retry", "skipped")]:
                    if bool(v):
                        serialized_op["partial_kwargs"][f"has_{k}"] = True
                    continue
                serialized_op["partial_kwargs"].update({k: BaseSerialization.serialize(v)})
        
        # we want to store python_callable_name, not python_callable
        python_callable = op.partial_kwargs.get("python_callable", None)
        if python_callable:
            callable_name = qualname(python_callable)
            serialized_op["partial_kwargs"]["python_callable_name"] = callable_name
            del serialized_op["partial_kwargs"]["python_callable"]
        
        serialized_op["_is_mapped"] = True
        return serialized_op

    def _serialize_node(self, op: BaseOperator | MappedOperator) -> dict[str, Any]:
        """Serialize operator into a JSON object (shared logic)."""
        return self.serialize_operator_fields(op, self._decorated_fields)

    def serialize_operator_fields(self, op: BaseOperator | MappedOperator, decorated_fields: set) -> dict[str, Any]:
        """Serialize operator fields (replaces serialize_to_json logic)."""
        from airflow.serialization.serialized_objects import BaseSerialization
        
        serialized_object: dict[str, Any] = {}
        keys_to_serialize = op.get_serialized_fields()
        for key in keys_to_serialize:
            # None is ignored in serialized form and is added back in deserialization.
            value = getattr(op, key, None)
            if self._is_excluded(value, key, op):
                continue
            
            if key == "_operator_name":
                # when operator_name matches task_type, we can remove
                # it to reduce the JSON payload
                task_type = getattr(op, "task_type", None)
                if value != task_type:
                    serialized_object[key] = BaseSerialization.serialize(value)
            elif key in decorated_fields:
                serialized_object[key] = BaseSerialization.serialize(value)
            elif key == "timetable" and value is not None:
                from airflow.serialization.serialized_objects import encode_timetable
                serialized_object[key] = encode_timetable(value)
            elif key == "weight_rule" and value is not None:
                from airflow.serialization.serialized_objects import encode_priority_weight_strategy
                encoded_priority_weight_strategy = encode_priority_weight_strategy(value)
                
                # Exclude if it is just default
                default_pri_weight_stra = self._get_schema_defaults("operator").get(key, None)
                if default_pri_weight_stra != encoded_priority_weight_strategy:
                    serialized_object[key] = encoded_priority_weight_strategy
                
            else:
                value = BaseSerialization.serialize(value)
                if isinstance(value, dict) and Encoding.TYPE in value:
                    value = value[Encoding.VAR]
                serialized_object[key] = value
        return serialized_object
    
    def _is_excluded(self, var: Any, attrname: str, op: BaseOperator | MappedOperator) -> bool:
        """Check if field should be excluded from serialization."""
        # Avoid circular imports
        from airflow.serialization.serialized_objects import SerializedBaseOperator
        return SerializedBaseOperator._is_excluded(var, attrname, op)
    
    def _get_schema_defaults(self, object_type: str) -> dict[str, Any]:
        """Get schema defaults for the object type."""
        # Avoid circular imports
        from airflow.serialization.serialized_objects import BaseSerialization
        return BaseSerialization.get_schema_defaults(object_type)
    
    def _serialize_operator_extra_links(self, operator_extra_links) -> dict[str, str]:
        """
        Serialize Operator Links.
        
        Store the "name" of the link mapped with the xcom_key which can be later used to retrieve this
        operator extra link from XComs.
        For example:
        ``{'link-name-1': 'xcom-key-1'}``
        
        :param operator_extra_links: Operator Link
        :return: Serialized Operator Link
        """
        return {link.name: link.xcom_key for link in operator_extra_links}
