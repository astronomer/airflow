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
import re

from airflow.api_fastapi.core_api.datamodels.providers import ProviderResponse
from airflow.providers_manager import ProviderInfo

log = logging.getLogger(__name__)


def _remove_rst_syntax(value: str) -> str:
    return re.sub("[`_<>]", "", value.strip(" \n."))


def _provider_mapper(provider: ProviderInfo) -> ProviderResponse:
    return ProviderResponse(
        package_name=provider.data["package-name"],
        description=_remove_rst_syntax(provider.data["description"]),
        version=provider.version,
        documentation_url=provider.data["documentation-url"],
    )


def get_merged_providers() -> list[ProviderResponse]:
    """
    Merge locally installed providers with worker-reported providers.

    Worker-only providers (not installed on the API server) are included with
    basic metadata.  Each provider gets a ``workers`` list of worker IDs that
    reported having it installed.
    """
    from airflow.providers_manager import ProvidersManager

    local_providers: dict[str, ProviderResponse] = {
        p.package_name: p for p in (_provider_mapper(info) for info in ProvidersManager().providers.values())
    }

    worker_data = _get_worker_provider_data()

    for pkg_name, info in worker_data.items():
        if pkg_name in local_providers:
            local_providers[pkg_name].workers = info["workers"]
        else:
            local_providers[pkg_name] = ProviderResponse(
                package_name=pkg_name,
                description="",
                version=info["version"],
                documentation_url=None,
                workers=info["workers"],
            )

    return sorted(local_providers.values(), key=lambda p: p.package_name)


def _get_worker_provider_data() -> dict[str, dict]:
    """Return {package_name: {"version": str, "workers": [str]}} from the worker inventory."""
    try:
        from airflow.api_fastapi.execution_api.services.worker_inventory import worker_inventory

        result: dict[str, dict] = {}
        for provider_name, versions in worker_inventory._provider_cache.items():
            workers: set[str] = set()
            for worker_list in versions.values():
                workers.update(worker_list)
            latest_version = sorted(versions.keys())[-1] if versions else ""
            result[provider_name] = {
                "version": latest_version,
                "workers": sorted(workers),
            }
        return result
    except Exception:
        log.debug("Worker inventory not available", exc_info=True)
        return {}
