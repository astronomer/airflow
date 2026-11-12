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
"""The secrets backend of a project whose ``pyproject.toml`` names one in ``[tool.airflow.secrets]``."""

from __future__ import annotations

import logging
from typing import Any

from airflow._shared.module_loading import import_string
from airflow._shared.secrets_backend.base import (
    BaseSecretsBackend as AnySecretsBackend,
    call_secrets_backend_method,
)
from airflow.sdk.exceptions import AirflowSecretsBackendAccessDenied
from airflow.secrets.base_secrets import BaseSecretsBackend
from airflow.secrets.local_filesystem import LocalFilesystemBackend

log = logging.getLogger(__name__)


class LocalRunSecretsBackend(BaseSecretsBackend):
    """
    Look in the run's connections and variables files, then in the backend the project names.

    Airflow takes one custom backend, and the Dag file code a run imports, its tasks and the Execution API must
    all look in both, in this order.

    Keyword arguments other than these are Airflow's per-key ``AIRFLOW__SECRETS__BACKEND_KWARG__*`` settings
    for the project's backend.
    """

    def __init__(
        self,
        *,
        backend: str,
        backend_kwargs: dict[str, Any] | None = None,
        connections_file_path: str | None = None,
        variables_file_path: str | None = None,
        **backend_kwarg_overrides: str,
    ) -> None:
        super().__init__()
        self.backend_path = backend
        self.backend_kwargs = {**(backend_kwargs or {}), **backend_kwarg_overrides}
        self.connections_file_path = connections_file_path
        self.variables_file_path = variables_file_path
        self._backends: list[AnySecretsBackend] | None = None

    def get_backends(self) -> list[AnySecretsBackend]:
        """
        Return the backends to look in, in order, creating them on first use.

        Airflow creates this backend while it starts in every process of the project, so creating the
        project's there would let a provider missing from the project stop all of them.
        """
        if self._backends is None:
            backends: list[AnySecretsBackend] = []
            if self.connections_file_path or self.variables_file_path:
                backends.append(
                    LocalFilesystemBackend(
                        variables_file_path=self.variables_file_path,
                        connections_file_path=self.connections_file_path,
                    )
                )
            backends.append(import_string(self.backend_path)(**self.backend_kwargs))
            for backend in backends:
                backend._set_connection_class(self._get_connection_class())
            self._backends = backends
        return self._backends

    def get_connection(self, conn_id: str, team_name: str | None = None) -> Any:
        return self._look_up("get_connection", team_name=team_name, conn_id=conn_id)

    def get_variable(self, key: str, team_name: str | None = None) -> str | None:
        return self._look_up("get_variable", team_name=team_name, key=key)

    def get_config(self, key: str) -> str | None:
        return self._look_up("get_config", team_name=None, key=key)

    def _look_up(self, method: str, *, team_name: str | None, **kwargs: str) -> Any:
        """Ask each backend in turn, as Airflow asks its backends: a failing one is skipped, a denial is final."""
        for backend in self.get_backends():
            try:
                value = call_secrets_backend_method(getattr(backend, method), team_name=team_name, **kwargs)
            except AirflowSecretsBackendAccessDenied:
                raise
            except Exception:
                log.debug(
                    "Unable to look up %s in secrets backend (%s). Checking subsequent secrets backend.",
                    kwargs,
                    type(backend).__name__,
                    exc_info=True,
                )
                continue
            if value is not None:
                return value
        return None
