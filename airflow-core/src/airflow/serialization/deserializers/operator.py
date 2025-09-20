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
"""Deserializer for operators."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from airflow.exceptions import AirflowException
from airflow.models.xcom import XComModel
from airflow.serialization.deserializers.base import BaseDeserializer
# decode functions are imported later to avoid circular import

if TYPE_CHECKING:
    from airflow.models.mappedoperator import MappedOperator as SerializedMappedOperator
    from airflow.sdk import BaseOperatorLink
    from airflow.serialization.serialized_objects import SerializedBaseOperator, SerializedDAG, SerializedOperator


class OperatorDeserializer:
    """Handles deserialization of operators."""
    
    def __init__(self, base_deserializer: BaseDeserializer):
        self.base = base_deserializer
        self._load_operator_extra_links = True
    
    def deserialize_operator(
        self, 
        encoded_op: dict[str, Any], 
        client_defaults: dict[str, Any] | None = None
    ) -> SerializedOperator:
        """Deserialize operator data into SerializedBaseOperator or MappedOperator."""
        from airflow.models.mappedoperator import MappedOperator as SerializedMappedOperator
        from airflow.serialization.serialized_objects import SerializedBaseOperator
        
        op: SerializedOperator
        if encoded_op.get("_is_mapped", False):
            try:
                operator_name = encoded_op["_operator_name"]
            except KeyError:
                operator_name = encoded_op["task_type"]
            
            # Only store minimal class type information instead of full operator data
            # This significantly reduces memory usage for mapped operators
            operator_class_info = {
                "task_type": encoded_op["task_type"],
                "_operator_name": operator_name,
            }
            
            op = SerializedMappedOperator(
                operator_class=operator_class_info,
                task_id=encoded_op["task_id"],
                operator_extra_links=SerializedBaseOperator.operator_extra_links,
                template_ext=SerializedBaseOperator.template_ext,
                template_fields=SerializedBaseOperator.template_fields,
                template_fields_renderers=SerializedBaseOperator.template_fields_renderers,
                ui_color=SerializedBaseOperator.ui_color,
                ui_fgcolor=SerializedBaseOperator.ui_fgcolor,
                is_sensor=encoded_op.get("_is_sensor", False),
                can_skip_downstream=encoded_op.get("_can_skip_downstream", False),
                task_module=encoded_op["_task_module"],
                task_type=encoded_op["task_type"],
                operator_name=operator_name,
                disallow_kwargs_override=encoded_op["_disallow_kwargs_override"],
                expand_input_attr=encoded_op["_expand_input_attr"],
                start_trigger_args=encoded_op.get("start_trigger_args", None),
                start_from_trigger=encoded_op.get("start_from_trigger", False),
            )
        else:
            op = SerializedBaseOperator(task_id=encoded_op["task_id"])
        
        self.populate_operator_fields(op, encoded_op, client_defaults)
        
        return op
    
    def populate_operator_fields(
        self, 
        op: SerializedOperator, 
        encoded_op: dict[str, Any],
        client_defaults: dict[str, Any] | None = None
    ) -> None:
        """Populate operator fields from serialized data."""
        from airflow.serialization.serialized_objects import (
            _ExpandInputRef,
            BaseSerialization,
            SerializedBaseOperator
        )
        from airflow.ti_deps.deps.ready_to_reschedule import ReadyToRescheduleDep
        
        # Apply defaults by merging them into encoded_op BEFORE main deserialization
        encoded_op = SerializedBaseOperator._apply_defaults_to_encoded_op(encoded_op, client_defaults)
        
        # Preprocess and upgrade all field names for backward compatibility and consistency
        encoded_op = self._preprocess_encoded_operator(encoded_op)
        # Extra Operator Links defined in Plugins
        op_extra_links_from_plugin = {}
        
        # We don't want to load Extra Operator links in Scheduler
        if self._load_operator_extra_links:
            from airflow import plugins_manager
            
            plugins_manager.initialize_extra_operators_links_plugins()
            
            if plugins_manager.operator_extra_links is None:
                raise AirflowException("Can not load plugins")
            
            for ope in plugins_manager.operator_extra_links:
                for operator in ope.operators:
                    if (
                        operator.__name__ == encoded_op["task_type"]
                        and operator.__module__ == encoded_op["_task_module"]
                    ):
                        op_extra_links_from_plugin.update({ope.name: ope})
            
            # If OperatorLinks are defined in Plugins but not in the Operator that is being Serialized
            # set the Operator links attribute
            # The case for "If OperatorLinks are defined in the operator that is being Serialized"
            # is handled in the deserialization loop where it matches k == "_operator_extra_links"
            if op_extra_links_from_plugin and "_operator_extra_links" not in encoded_op:
                setattr(
                    op,
                    "operator_extra_links",
                    list(op_extra_links_from_plugin.values()),
                )
        
        deserialized_partial_kwarg_defaults = {}
        
        for k, v in encoded_op.items():
            # Use centralized field deserialization logic
            if k in encoded_op.get("template_fields", []):
                pass  # Template fields are handled separately
            elif k == "_operator_extra_links":
                if self._load_operator_extra_links:
                    op_predefined_extra_links = self._deserialize_operator_extra_links(v)
                    
                    # If OperatorLinks with the same name exists, Links via Plugin have higher precedence
                    op_predefined_extra_links.update(op_extra_links_from_plugin)
                else:
                    op_predefined_extra_links = {}
                
                v = list(op_predefined_extra_links.values())
                k = "operator_extra_links"
                
            elif k == "params":
                v = BaseSerialization._deserialize_params_dict(v)
                if op.params:  # Merge existing params if needed.
                    v, new = op.params, v
                    v.update(new)
            elif k == "partial_kwargs":
                # Use unified deserializer that supports both encoded and non-encoded values
                v = SerializedBaseOperator._deserialize_partial_kwargs(v, client_defaults)
            elif k in {"expand_input", "op_kwargs_expand_input"}:
                v = _ExpandInputRef(v["type"], BaseSerialization.deserialize(v["value"]))
            elif k == "operator_class":
                v = {k_: BaseSerialization.deserialize(v_) for k_, v_ in v.items()}
            elif k == "_is_sensor":
                if v is False:
                    raise RuntimeError("_is_sensor=False should never have been serialized!")
                object.__setattr__(op, "deps", op.deps | {ReadyToRescheduleDep()})
                continue
            elif (
                k in SerializedBaseOperator._decorated_fields
                or k not in op.get_serialized_fields()
                or k in ("outlets", "inlets")
            ):
                v = BaseSerialization.deserialize(v)
            elif k == "_on_failure_fail_dagrun":
                k = "on_failure_fail_dagrun"
            elif k == "weight_rule":
                k = "_weight_rule"
                from airflow.serialization.serialized_objects import decode_priority_weight_strategy
                v = decode_priority_weight_strategy(v)
            else:
                # Apply centralized deserialization for all other fields
                v = SerializedBaseOperator._deserialize_field_value(k, v)
            
            # Handle field differences between SerializedBaseOperator and MappedOperator
            # Fields that exist in SerializedBaseOperator but not in MappedOperator need to go to partial_kwargs
            if (
                op.is_mapped
                and k in SerializedBaseOperator.get_serialized_fields()
                and k not in op.get_serialized_fields()
            ):
                # This field belongs to SerializedBaseOperator but not MappedOperator
                # Store it in partial_kwargs where it belongs
                deserialized_partial_kwarg_defaults[k] = v
                continue
            
            # else use v as it is
            setattr(op, k, v)
        
        # Apply the fields that belong in partial_kwargs for MappedOperator
        if op.is_mapped:
            for k, v in deserialized_partial_kwarg_defaults.items():
                if k not in op.partial_kwargs:
                    op.partial_kwargs[k] = v
        
        for k in op.get_serialized_fields() - encoded_op.keys():
            # TODO: refactor deserialization of BaseOperator and MappedOperator (split it out), then check
            # could go away.
            if not hasattr(op, k):
                setattr(op, k, None)
        
        # Set all the template_field to None that were not present in Serialized JSON
        for field in op.template_fields:
            if not hasattr(op, field):
                setattr(op, field, None)
        
        # Used to determine if an Operator is inherited from EmptyOperator
        setattr(op, "_is_empty", bool(encoded_op.get("_is_empty", False)))
        
        # Used to determine if an Operator is inherited from SkipMixin
        setattr(op, "_can_skip_downstream", bool(encoded_op.get("_can_skip_downstream", False)))
        
        start_trigger_args = None
        encoded_start_trigger_args = encoded_op.get("start_trigger_args", None)
        if encoded_start_trigger_args:
            encoded_start_trigger_args = cast("dict", encoded_start_trigger_args)
            from airflow.serialization.serialized_objects import decode_start_trigger_args
            start_trigger_args = decode_start_trigger_args(encoded_start_trigger_args)
        setattr(op, "start_trigger_args", start_trigger_args)
        setattr(op, "start_from_trigger", bool(encoded_op.get("start_from_trigger", False)))
    
    def _preprocess_encoded_operator(self, encoded_op: dict[str, Any]) -> dict[str, Any]:
        """Handle backward compatibility field transformations."""
        preprocessed = encoded_op.copy()
        
        # Handle callback field renaming for backward compatibility
        for callback_type in ("execute", "failure", "success", "retry", "skipped"):
            old_key = f"on_{callback_type}_callback"
            new_key = f"has_{old_key}"
            if old_key in preprocessed:
                preprocessed[new_key] = bool(preprocessed[old_key])
                del preprocessed[old_key]
        
        # Handle other field renames and upgrades from old format/name
        field_renames = {
            "task_display_name": "_task_display_name",
            "_downstream_task_ids": "downstream_task_ids",
            "_task_type": "task_type",
            "_outlets": "outlets",
            "_inlets": "inlets",
        }
        
        for old_name, new_name in field_renames.items():
            if old_name in preprocessed:
                preprocessed[new_name] = preprocessed.pop(old_name)
        
        # Remove fields that shouldn't be processed
        fields_to_exclude = {
            "python_callable_name",  # Only serves to detect function name changes
            "label",  # Shouldn't be set anymore - computed from task_id now
        }
        
        for field in fields_to_exclude:
            preprocessed.pop(field, None)
        
        return preprocessed
    
    def _deserialize_operator_extra_links(
        self, encoded_op_links: dict[str, str]
    ) -> dict[str, BaseOperatorLink]:
        """
        Deserialize Operator Links if the Classes are registered in Airflow Plugins.
        
        Error is raised if the OperatorLink is not found in Plugins too.
        
        :param encoded_op_links: Serialized Operator Link
        :return: De-Serialized Operator Link
        """
        from airflow import plugins_manager
        from airflow.serialization.serialized_objects import XComOperatorLink
        
        plugins_manager.initialize_extra_operators_links_plugins()
        
        if plugins_manager.registered_operator_link_classes is None:
            raise AirflowException("Can't load plugins")
        op_predefined_extra_links = {}
        
        for name, xcom_key in encoded_op_links.items():
            # Get the name and xcom_key of the encoded operator and use it to create a XComOperatorLink object
            # during deserialization.
            #
            # Example:
            # enc_operator['_operator_extra_links'] =
            # {
            #     'airflow': 'airflow_link_key',
            #     'foo-bar': 'link-key',
            #     'no_response': 'key',
            #     'raise_error': 'key'
            # }
            
            op_predefined_extra_link = XComOperatorLink(name=name, xcom_key=xcom_key)
            op_predefined_extra_links.update({op_predefined_extra_link.name: op_predefined_extra_link})
        
        return op_predefined_extra_links
