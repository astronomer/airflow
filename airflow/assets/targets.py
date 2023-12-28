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

import pathlib
import typing

import attrs
import jinja2

from airflow.hooks.base import BaseHook
from airflow.io.path import ObjectStoragePath

if typing.TYPE_CHECKING:
    import pandas
    import sqlalchemy.engine

    from airflow.assets.fileformats import FileFormat
    from airflow.typing_compat import Literal, TypeGuard
    from airflow.utils.context import Context


@attrs.define()
class Template:
    """Value template to be passed into various things.

    Unfortunately we can't just use ``jinja2.Template`` since it does not keep
    the original template string.
    """

    source: str

    def render(self, context: Context) -> str:
        return jinja2.Template(self.source).render(context)


def _is_pandas_dataframe(obj: typing.Any) -> TypeGuard[pandas.DataFrame]:
    try:
        import pandas
    except ModuleNotFoundError:
        return False
    return isinstance(obj, pandas.DataFrame)


class AssetTarget(typing.Protocol):
    """Base representation of a target where an asset writes to."""

    def as_dataset_uri(self) -> str:
        raise NotImplementedError

    def read_pandas_dataframe(self, context: Context) -> pandas.DataFrame:
        raise NotImplementedError

    def write_pandas_dataframe(self, data: pandas.DataFrame, context: Context) -> None:
        raise NotImplementedError

    def write_data(self, data: typing.Any, context: Context) -> None:
        if _is_pandas_dataframe(data):
            return self.write_pandas_dataframe(data, context)
        raise TypeError(f"cannot write data of type {type(data).__name__!r}")


@attrs.define()
class File(AssetTarget):
    """File target to write into."""

    path: str | ObjectStoragePath | Template
    fmt: FileFormat = attrs.field(kw_only=True)

    def as_dataset_uri(self) -> str:
        p = self.path
        if isinstance(p, ObjectStoragePath):
            return p.as_uri()
        # TODO: Depending on a templated asset location means the dataset URI
        # is an unrendered template string. This also requires a dataset event
        # to be emitted with that exact string (instead of the rendered value),
        # which is not yet done.
        if isinstance(p, Template):
            return p.source
        return p

    def _render_storage_path(self, context: Context) -> ObjectStoragePath:
        p = self.path
        if isinstance(p, ObjectStoragePath):
            return p
        if isinstance(p, Template):
            return ObjectStoragePath(p.render(context))
        return ObjectStoragePath(p)

    def read_pandas_dataframe(self, context: Context) -> pandas.DataFrame:
        return self.fmt.read_pandas_dataframe(self._render_storage_path(context))

    def write_pandas_dataframe(self, data: pandas.DataFrame, context: Context) -> None:
        return self.fmt.write_pandas_dataframe(self._render_storage_path(context), data)


@attrs.define()
class Table(AssetTarget):
    """Table (in a relational database) target to write into."""

    conn_id: str
    name: str = attrs.field(kw_only=True)
    mode: Literal["insert", "replace"] = attrs.field(kw_only=True)

    def _get_sqlalchemy_engine(self) -> sqlalchemy.engine.Engine:
        from airflow.providers.common.sql.hooks.sql import DbApiHook

        hook = BaseHook.get_connection(self.conn_id).get_hook()
        if not isinstance(hook, DbApiHook):
            raise RuntimeError(f"Connection {self.conn_id} does not point to a database")
        return hook.get_sqlalchemy_engine()

    def as_dataset_uri(self) -> str:
        # TODO: Put URI formatting logic into the providers, and use
        # ProvidersManager to dispatch logic.
        connection = BaseHook.get_connection(self.conn_id)
        if connection.conn_type != "sqlite":
            raise NotImplementedError("Only SQLite is supported at the moment")
        # A SQLite database is a file, so tables in it are tracked by its URI.
        # Don't try to understand this, Airflow Connection's URI logic is bs.
        if connection.host and not connection.host.startswith("/"):
            raise ValueError("can't use relative path in assets")
        return pathlib.Path(connection.host or "/", connection.schema or "").as_uri()

    def read_pandas_dataframe(self, context: Context) -> pandas.DataFrame:
        import pandas

        return pandas.read_sql_table(self.name, self._get_sqlalchemy_engine())

    def write_pandas_dataframe(self, data: pandas.DataFrame, context: Context) -> None:
        # TODO: Probably need to add some column filtering? Sometimes maybe
        # DataFrame metadata (e.g. index) shouldn't get into the database?

        def _as_pandas_if_exists() -> Literal["append", "replace"]:
            if self.mode == "insert":
                return "append"
            return self.mode

        data.to_sql(self.name, self._get_sqlalchemy_engine(), if_exists=_as_pandas_if_exists())
