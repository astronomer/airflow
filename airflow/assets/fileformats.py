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

if typing.TYPE_CHECKING:
    import pandas

    from airflow.io.path import ObjectStoragePath


class FileFormat(typing.Protocol):
    """Base file format."""

    def read_pandas_dataframe(self, path: ObjectStoragePath) -> pandas.DataFrame:
        raise NotImplementedError

    def write_pandas_dataframe(self, path: ObjectStoragePath, df: pandas.DataFrame) -> None:
        raise NotImplementedError


class ParquetFormat(FileFormat):
    """Parquet file format, generally with suffix ``.parquet``."""

    engine: typing.Literal["auto", "pyarrow", "fastparquet"] = "auto"
    compression: typing.Literal["snappy", "gzip", "brotli"] | None = "snappy"

    def read_pandas_dataframe(self, path: ObjectStoragePath) -> pandas.DataFrame:
        import pandas

        with path.open("rb") as f:
            return pandas.read_parquet(f, engine=self.engine)

    def write_pandas_dataframe(self, path: ObjectStoragePath, df: pandas.DataFrame) -> None:
        with path.open("wb") as f:
            df.to_parquet(f, engine=self.engine, compression=self.compression)
