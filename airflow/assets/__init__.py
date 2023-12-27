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

import typing

import attrs

from airflow.assets.assets import Asset

if typing.TYPE_CHECKING:
    from airflow.assets.targets import AssetTarget
    from airflow.timetables.base import Timetable

F = typing.TypeVar("F", bound=typing.Callable)


@attrs.define(kw_only=True)
class AssetDecorator:
    """Decorator to create an asset DAG."""

    at: AssetTarget
    schedule: str | Timetable | dict[str, Asset]

    def __call__(self, f: F) -> Asset[F]:
        return Asset(at=self.at, function=f, schedule=self.schedule)


# So we can do @asset(...) on a function.
asset = AssetDecorator
