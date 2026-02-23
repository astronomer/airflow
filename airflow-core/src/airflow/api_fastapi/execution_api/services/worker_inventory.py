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
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


class WorkerInventory:
    """
    In-memory inventory service for tracking worker provider information.

    For hackathon/POC: stores data in memory only.
    Production version: should persist to database and use in-memory cache.
    """

    def __init__(self):
        self._inventory: dict[str, dict[str, Any]] = {}
        self._provider_cache: dict[str, dict[str, Any]] = {}

    def register(self, worker_id: str, executor_type: str, providers: list[dict[str, str]]) -> None:
        """
        Register or update worker's provider information.

        Uses upsert strategy - updates if worker exists, creates if new.
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        self._inventory[worker_id] = {
            "worker_id": worker_id,
            "executor_type": executor_type,
            "providers": providers,
            "last_updated": timestamp,
        }

        # Update provider cache for fast lookups
        for provider in providers:
            provider_name = provider["name"]
            provider_version = provider["version"]

            if provider_name not in self._provider_cache:
                self._provider_cache[provider_name] = {}

            if provider_version not in self._provider_cache[provider_name]:
                self._provider_cache[provider_name][provider_version] = []

            # Track which workers have this provider version
            if worker_id not in self._provider_cache[provider_name][provider_version]:
                self._provider_cache[provider_name][provider_version].append(worker_id)

        log.info(f"Registered {len(providers)} providers for worker {worker_id} ({executor_type})")

    def get_worker(self, worker_id: str) -> dict[str, Any] | None:
        """Get worker information by ID."""
        return self._inventory.get(worker_id)

    def get_all_workers(self) -> list[dict[str, Any]]:
        """Get all registered workers."""
        return list(self._inventory.values())

    def get_all_providers(self) -> dict[str, dict[str, Any]]:
        """
        Get all unique providers with worker counts.

        Returns dict mapping provider_name to metadata including worker_count.
        """
        result = {}
        for provider_name, versions in self._provider_cache.items():
            # Count unique workers across all versions
            all_workers = set()
            for workers_list in versions.values():
                all_workers.update(workers_list)

            result[provider_name] = {
                "name": provider_name,
                "versions": list(versions.keys()),
                "worker_count": len(all_workers),
            }

        return result

    def get_provider_version_workers(self, provider_name: str, version: str) -> list[str]:
        """Get list of worker IDs that have a specific provider version."""
        return self._provider_cache.get(provider_name, {}).get(version, [])

    def remove_worker(self, worker_id: str) -> None:
        """Remove worker from inventory (e.g., on worker shutdown)."""
        if worker_id in self._inventory:
            # Clean up provider cache
            worker_info = self._inventory[worker_id]
            for provider in worker_info.get("providers", []):
                provider_name = provider["name"]
                provider_version = provider["version"]

                if provider_name in self._provider_cache:
                    if provider_version in self._provider_cache[provider_name]:
                        workers = self._provider_cache[provider_name][provider_version]
                        if worker_id in workers:
                            workers.remove(worker_id)

                        # Clean up empty entries
                        if not workers:
                            del self._provider_cache[provider_name][provider_version]

                    if not self._provider_cache[provider_name]:
                        del self._provider_cache[provider_name]

            del self._inventory[worker_id]
            log.info(f"Removed worker {worker_id} from inventory")

    def clear(self) -> None:
        """Clear all inventory data (useful for testing)."""
        self._inventory.clear()
        self._provider_cache.clear()


# Global singleton instance
worker_inventory = WorkerInventory()
