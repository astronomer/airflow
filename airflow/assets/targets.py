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
import jinja2

from airflow.io.path import ObjectStoragePath

if typing.TYPE_CHECKING:
    import pandas

    from airflow.assets.fileformats import FileFormat
    from airflow.typing_compat import TypeGuard
    from airflow.utils.context import Context


def _is_pandas_dataframe(obj: typing.Any) -> TypeGuard[pandas.DataFrame]:
    try:
        import pandas
    except ModuleNotFoundError:
        return False
    return isinstance(obj, pandas.DataFrame)


class AssetTarget(typing.Protocol):
    """Base representation of a target where an asset writes to."""

    def _write_pandas_dataframe(self, data: pandas.DataFrame, context: Context) -> None:
        raise NotImplementedError

    def write_data(self, data: typing.Any, context: Context) -> None:
        if _is_pandas_dataframe(data):
            return self._write_pandas_dataframe(data, context)
        raise TypeError(f"cannot write data of type {type(data).__name__!r}")


@attrs.define()
class File(AssetTarget):
    """File target to write into."""

    path: str | ObjectStoragePath | jinja2.Template
    fmt: FileFormat

    def _get_storage_path(self, context: Context) -> ObjectStoragePath:
        p = self.path
        if isinstance(p, ObjectStoragePath):
            return p
        if isinstance(p, jinja2.Template):
            return ObjectStoragePath(p.render(**context))
        return ObjectStoragePath(p)

    def _write_pandas_dataframe(self, data: pandas.DataFrame, context: Context) -> None:
        return self.fmt.write_pandas_dataframe(self._get_storage_path(context), data)
