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

from __future__ import annotations

import logging
from typing import Any

from airflow.api_fastapi.core_api.datamodels.connections import (
    ConnectionHookFieldBehavior,
    ConnectionHookMetaData,
    StandardHookFields,
)

log = logging.getLogger(__name__)


class HookMetaService:
    """
    Service for retrieving hook / connection-type metadata to render the UI.

    Reads from the ProviderMetadataFetcher cache which is populated when
    workers register their installed providers.  No dependency on
    ProvidersManager or locally installed provider packages.
    """

    @staticmethod
    def hook_meta_data() -> list[ConnectionHookMetaData]:
        from airflow.api_fastapi.execution_api.services.provider_metadata_fetcher import (
            provider_metadata_fetcher,
        )

        remote_connection_types = provider_metadata_fetcher.get_all_connection_types()

        if not remote_connection_types:
            log.debug("No remote provider metadata cached yet (no workers registered?)")
            return []

        seen: set[str] = set()
        results: list[ConnectionHookMetaData] = []
        for ct in remote_connection_types:
            conn_type = ct.get("connection-type")
            if not conn_type or conn_type in seen:
                continue
            hook_meta = HookMetaService._from_yaml_connection_type(ct)
            if hook_meta:
                results.append(hook_meta)
                seen.add(conn_type)

        log.info("Serving %d connection type(s) from worker-discovered providers", len(results))
        return results

    @staticmethod
    def _from_yaml_connection_type(ct: dict[str, Any]) -> ConnectionHookMetaData | None:
        """
        Convert a ``connection-types`` entry from provider.yaml into a
        :class:`ConnectionHookMetaData`.
        """
        connection_type = ct.get("connection-type")
        hook_class = ct.get("hook-class-name")
        if not connection_type:
            return None

        hook_name = connection_type

        ui_behaviour = ct.get("ui-field-behaviour", {})
        standard_fields = HookMetaService._parse_ui_field_behaviour(ui_behaviour) if ui_behaviour else None

        extra_fields = (
            HookMetaService._parse_conn_fields(ct["conn-fields"]) if ct.get("conn-fields") else None
        )

        return ConnectionHookMetaData(
            connection_type=connection_type,
            hook_class_name=hook_class,
            default_conn_name=None,
            hook_name=hook_name,
            standard_fields=standard_fields,
            extra_fields=extra_fields,
        )

    @staticmethod
    def _parse_ui_field_behaviour(behaviour: dict[str, Any]) -> StandardHookFields:
        hidden = behaviour.get("hidden-fields", [])
        relabeling = behaviour.get("relabeling", {})
        placeholders = behaviour.get("placeholders", {})

        def _make(field_name: str) -> ConnectionHookFieldBehavior | None:
            is_hidden = field_name in hidden
            title = relabeling.get(field_name)
            placeholder = placeholders.get(field_name)
            if any([is_hidden, title, placeholder]):
                return ConnectionHookFieldBehavior(hidden=is_hidden, title=title, placeholder=placeholder)
            return None

        return StandardHookFields(
            description=_make("description"),
            url_schema=_make("schema"),
            host=_make("host"),
            port=_make("port"),
            login=_make("login"),
            password=_make("password"),
        )

    @staticmethod
    def _parse_conn_fields(conn_fields: dict[str, Any]) -> dict[str, Any]:
        """
        Convert conn-fields from provider.yaml into the extra_fields format
        the UI expects.

        Matches the output of ``ProvidersManager._to_api_format()``::

            {"value": default, "schema": {"type": ..., "title": label}, "description": ..., "source": None}
        """
        result: dict[str, Any] = {}
        for field_name, field_def in conn_fields.items():
            schema_def = field_def.get("schema", {})
            schema = schema_def.copy()
            if "label" in field_def:
                schema["title"] = field_def["label"]
            result[field_name] = {
                "value": schema_def.get("default"),
                "schema": schema,
                "description": field_def.get("description"),
                "source": None,
            }
        return result
