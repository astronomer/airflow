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
    
    For heterogeneous workers with different versions, creates separate rows
    per (package_name, version) combination.
    """
    from airflow.providers_manager import ProvidersManager

    local_providers: dict[str, ProviderResponse] = {
        p.package_name: p for p in (_provider_mapper(info) for info in ProvidersManager().providers.values())
    }

    worker_data = _get_worker_provider_data()

    result: dict[str, ProviderResponse] = {}
    
    for key, info in worker_data.items():
        # key format: "package_name::version" for worker providers
        if "::" in key:
            pkg_name, version = key.rsplit("::", 1)
            # Use package_name::version as unique key for result
            if key in result:
                # Already added (shouldn't happen but be safe)
                continue
            
            # Check if we have local provider info for base metadata
            if pkg_name in local_providers:
                base_provider = local_providers[pkg_name]
                result[key] = ProviderResponse(
                    package_name=pkg_name,
                    description=base_provider.description,
                    version=version,  # Use version from worker
                    documentation_url=base_provider.documentation_url,
                    workers=info["workers"],
                    is_custom=info.get("is_custom", False),
                )
            else:
                # Worker-only provider (not installed locally)
                result[key] = ProviderResponse(
                    package_name=pkg_name,
                    description="",
                    version=version,
                    documentation_url=None,
                    workers=info["workers"],
                    is_custom=info.get("is_custom", False),
                )
        else:
            # Fallback for old format (shouldn't happen with new code)
            pkg_name = key
            if pkg_name in local_providers:
                local_providers[pkg_name].workers = info["workers"]
                if info.get("is_custom"):
                    local_providers[pkg_name].is_custom = True
                result[pkg_name] = local_providers[pkg_name]
            else:
                result[pkg_name] = ProviderResponse(
                    package_name=pkg_name,
                    description="",
                    version=info["version"],
                    documentation_url=None,
                    workers=info["workers"],
                    is_custom=info.get("is_custom", False),
                )

    return sorted(result.values(), key=lambda p: (p.package_name, p.version))


def _get_worker_provider_data() -> dict[str, dict]:
    """
    Return provider data from worker inventory.
    
    For heterogeneous workers, creates separate entries per version:
    {package_name::version: {"version": str, "workers": [str], "is_custom": bool}}
    """
    try:
        from airflow.api_fastapi.execution_api.services.worker_inventory import worker_inventory

        result: dict[str, dict] = {}
        for provider_name, versions in worker_inventory._provider_cache.items():
            # Create separate entry for each version instead of merging
            for version, version_entry in versions.items():
                # Use package_name::version as key to create separate entries
                key = f"{provider_name}::{version}"
                result[key] = {
                    "version": version,
                    "workers": sorted(version_entry["workers"]),
                    "is_custom": version_entry.get("is_custom", False),
                }
        
        # Debug logging for Pokemon provider
        pokemon_entries = {k: v for k, v in result.items() if "pokemon" in k.lower()}
        if pokemon_entries:
            log.info(f"[DEBUG] Pokemon provider entries: {pokemon_entries}")
        
        return result
    except Exception:
        log.debug("Worker inventory not available", exc_info=True)
        return {}
