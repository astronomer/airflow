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

import concurrent.futures
import logging
import threading
from typing import Any

import httpx
import yaml

from airflow.configuration import conf

log = logging.getLogger(__name__)

_DEFAULT_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/apache/airflow/main/providers/{provider_path}/provider.yaml"
)

_POOL_SIZE = 12


def _package_name_to_provider_path(package_name: str) -> str:
    """
    Convert a pip package name to the repo provider path.

    Examples:
        apache-airflow-providers-google       -> google
        apache-airflow-providers-cncf-kubernetes -> cncf/kubernetes
        apache-airflow-providers-common-sql    -> common/sql
    """
    prefix = "apache-airflow-providers-"
    if not package_name.startswith(prefix):
        return package_name.replace("-", "/")
    return package_name[len(prefix) :].replace("-", "/")


def _fetch_one_provider(
    client: httpx.Client,
    package_name: str,
    version: str,
    url: str,
) -> tuple[str, str, list[dict[str, Any]]]:
    """
    Fetch a single provider.yaml and return (package_name, version, connection_types).

    Runs inside a thread pool worker — must be self-contained.
    """
    try:
        resp = client.get(url)
        resp.raise_for_status()
        data = yaml.safe_load(resp.text)
        connection_types = data.get("connection-types", [])
        log.debug("Fetched %d connection-type(s) for %s", len(connection_types), package_name)
        return package_name, version, connection_types
    except httpx.HTTPStatusError as exc:
        log.warning("HTTP %s fetching %s: %s", exc.response.status_code, package_name, url)
        return package_name, version, []
    except Exception:
        log.warning("Failed to fetch %s", package_name, exc_info=True)
        return package_name, version, []


class ProviderMetadataFetcher:
    """
    Fetches and caches provider connection metadata from a remote source.

    Default source is the raw provider.yaml on GitHub. The URL template is
    configurable via ``[providers] metadata_url_template`` so it can be
    swapped to a provider registry endpoint in the future.

    Cache key is ``(package_name, version)``. A fetch is skipped when the
    same version is already cached.  Fetches are parallelized using a
    thread pool (similar to ``fetch_inventories`` in the docs build).
    """

    def __init__(self, url_template: str | None = None):
        self._url_template = url_template or conf.get(
            "providers",
            "metadata_url_template",
            fallback=_DEFAULT_URL_TEMPLATE,
        )
        # {(package_name, version): [connection_type_dict, ...]}
        self._cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def _build_url(self, package_name: str, version: str) -> str:
        provider_path = _package_name_to_provider_path(package_name)
        return self._url_template.format(
            provider_path=provider_path,
            package_name=package_name,
            version=version,
        )

    def is_cached(self, package_name: str, version: str) -> bool:
        return (package_name, version) in self._cache

    def fetch_many_in_background(self, providers: list[dict[str, str]]) -> None:
        """
        Kick off a background thread that fetches provider.yaml files in parallel.

        Only providers not already cached (at the same version) are fetched.
        Each provider dict must have 'name' and 'version' keys.
        """
        to_fetch = [p for p in providers if not self.is_cached(p["name"], p["version"])]
        if not to_fetch:
            log.debug("All %d providers already cached, skipping fetch", len(providers))
            return

        log.info("Scheduling background parallel fetch for %d provider(s)", len(to_fetch))
        thread = threading.Thread(
            target=self._fetch_batch_parallel,
            args=(to_fetch,),
            daemon=True,
            name="provider-metadata-fetcher",
        )
        thread.start()

    def _fetch_batch_parallel(self, providers: list[dict[str, str]]) -> None:
        """Fetch many provider.yaml files concurrently using a thread pool + shared httpx session."""
        succeeded = 0
        failed = 0

        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            with concurrent.futures.ThreadPoolExecutor(max_workers=_POOL_SIZE) as pool:
                futures = {
                    pool.submit(
                        _fetch_one_provider,
                        client,
                        p["name"],
                        p["version"],
                        self._build_url(p["name"], p["version"]),
                    ): p
                    for p in providers
                }

                for future in concurrent.futures.as_completed(futures):
                    package_name, version, connection_types = future.result()
                    key = (package_name, version)

                    with self._lock:
                        # Evict old versions of the same package
                        for cached_key in list(self._cache):
                            if cached_key[0] == package_name and cached_key[1] != version:
                                del self._cache[cached_key]
                        self._cache[key] = connection_types

                    if connection_types:
                        succeeded += 1
                    else:
                        failed += 1

        log.info(
            "Background fetch complete: %d with connection types, %d empty/failed out of %d total",
            succeeded,
            failed,
            len(providers),
        )

    def get_all_connection_types(self) -> list[dict[str, Any]]:
        """Return all cached connection-types across all providers (flat list)."""
        result: list[dict[str, Any]] = []
        for conn_types in self._cache.values():
            result.extend(conn_types)
        return result

    def get_connection_types_for(self, package_name: str, version: str) -> list[dict[str, Any]]:
        """Return cached connection-types for a specific provider version."""
        return self._cache.get((package_name, version), [])

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


# Global singleton
provider_metadata_fetcher = ProviderMetadataFetcher()
