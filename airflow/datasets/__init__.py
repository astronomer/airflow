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

import os
import urllib.parse
import warnings
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Iterable, Iterator, cast

import attr
from sqlalchemy import select

from airflow.api_internal.internal_api_call import internal_api_call
from airflow.serialization.dag_dependency import DagDependency
from airflow.typing_compat import TypedDict
from airflow.utils.session import NEW_SESSION, provide_session

if TYPE_CHECKING:
    from urllib.parse import SplitResult

    from sqlalchemy.orm.session import Session


from airflow.configuration import conf

__all__ = ["Dataset", "DatasetAll", "DatasetAny"]


def normalize_noop(parts: SplitResult) -> SplitResult:
    """
    Place-hold a :class:`~urllib.parse.SplitResult`` normalizer.

    :meta private:
    """
    return parts


def _get_uri_normalizer(scheme: str) -> Callable[[SplitResult], SplitResult] | None:
    if scheme == "file":
        return normalize_noop
    from airflow.providers_manager import ProvidersManager

    return ProvidersManager().dataset_uri_handlers.get(scheme)


def _get_normalized_scheme(uri: str) -> str:
    parsed = urllib.parse.urlsplit(uri)
    return parsed.scheme.lower()


class _IdentifierValidator:
    @staticmethod
    def validate(kind: str, value: str | None, *, optional: bool = False) -> None:
        if optional and value is None:
            return
        if not value:
            raise ValueError(f"{kind} cannot be empty")
        if len(value) > 3000:
            raise ValueError(f"{kind} must be at most 3000 characters")
        if value.isspace():
            raise ValueError(f"{kind} cannot be just whitespace")
        if not value.isascii():
            raise ValueError(f"{kind} must only consist of ASCII characters")

    def __call__(self, inst: Dataset | DatasetAlias, attribute: attr.Attribute, value: str | None) -> None:
        self.validate(
            f"{type(inst).__name__} {attribute.name}",
            value,
            optional=attribute.default is None,
        )


def _sanitize_uri(uri: str) -> str:
    """
    Sanitize a dataset URI.

    This checks for URI validity, and normalizes the URI if needed. A fully
    normalized URI is returned.
    """
    parsed = urllib.parse.urlsplit(uri)
    if not parsed.scheme and not parsed.netloc:  # Does not look like a URI.
        return uri
    if not (normalized_scheme := _get_normalized_scheme(uri)):
        return uri
    if normalized_scheme.startswith("x-"):
        return uri
    if normalized_scheme == "airflow":
        raise ValueError("Dataset scheme 'airflow' is reserved")
    _, auth_exists, normalized_netloc = parsed.netloc.rpartition("@")
    if auth_exists:
        # TODO: Collect this into a DagWarning.
        warnings.warn(
            "A dataset URI should not contain auth info (e.g. username or "
            "password). It has been automatically dropped.",
            UserWarning,
            stacklevel=3,
        )
    if parsed.query:
        normalized_query = urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(parsed.query)))
    else:
        normalized_query = ""
    parsed = parsed._replace(
        scheme=normalized_scheme,
        netloc=normalized_netloc,
        path=parsed.path.rstrip("/") or "/",  # Remove all trailing slashes.
        query=normalized_query,
        fragment="",  # Ignore any fragments.
    )
    if (normalizer := _get_uri_normalizer(normalized_scheme)) is not None:
        try:
            parsed = normalizer(parsed)
        except ValueError as exception:
            if conf.getboolean("core", "strict_dataset_uri_validation", fallback=False):
                raise
            warnings.warn(
                f"The dataset URI {uri} is not AIP-60 compliant: {exception}. "
                f"In Airflow 3, this will raise an exception.",
                UserWarning,
                stacklevel=3,
            )
    return urllib.parse.urlunsplit(parsed)


def extract_event_key(value: str | Dataset | DatasetAlias) -> str:
    """
    Extract the key of an inlet or an outlet event.

    If the input value is a string, it is treated as a URI and sanitized. If the
    input is a :class:`Dataset`, the URI it contains is considered sanitized and
    returned directly. If the input is a :class:`DatasetAlias`, the name it contains
    will be returned directly.

    :meta private:
    """
    if isinstance(value, DatasetAlias):
        return value.name
    if isinstance(value, Dataset):
        return value.uri
    _IdentifierValidator.validate("Dataset event key", uri := str(value))
    return _sanitize_uri(uri)


@internal_api_call
@provide_session
def expand_alias_to_datasets(
    alias: str | DatasetAlias, *, session: Session = NEW_SESSION
) -> list[BaseDataset]:
    """Expand dataset alias to resolved datasets."""
    from airflow.models.dataset import DatasetAliasModel

    alias_name = alias.name if isinstance(alias, DatasetAlias) else alias

    dataset_alias_obj = session.scalar(
        select(DatasetAliasModel).where(DatasetAliasModel.name == alias_name).limit(1)
    )
    if dataset_alias_obj:
        return [Dataset(uri=dataset.uri, extra=dataset.extra) for dataset in dataset_alias_obj.datasets]
    return []


class BaseDataset:
    """
    Protocol for all dataset triggers to use in ``DAG(schedule=...)``.

    :meta private:
    """

    def __bool__(self) -> bool:
        return True

    def __or__(self, other: BaseDataset) -> BaseDataset:
        if not isinstance(other, BaseDataset):
            return NotImplemented
        return DatasetAny(self, other)

    def __and__(self, other: BaseDataset) -> BaseDataset:
        if not isinstance(other, BaseDataset):
            return NotImplemented
        return DatasetAll(self, other)

    def as_expression(self) -> Any:
        """
        Serialize the dataset into its scheduling expression.

        The return value is stored in DagModel for display purposes. It must be
        JSON-compatible.

        :meta private:
        """
        raise NotImplementedError

    def evaluate(self, statuses: dict[str, bool]) -> bool:
        raise NotImplementedError

    def iter_datasets(self) -> Iterator[tuple[str, Dataset]]:
        raise NotImplementedError

    def iter_dataset_aliases(self) -> Iterator[DatasetAlias]:
        raise NotImplementedError

    def iter_dag_dependencies(self, *, source: str, target: str) -> Iterator[DagDependency]:
        """
        Iterate a base dataset as dag dependency.

        :meta private:
        """
        raise NotImplementedError


@attr.define()
class DatasetAlias(BaseDataset):
    """A represeation of dataset alias which is used to create dataset during the runtime."""

    name: str = attr.field(validator=_IdentifierValidator())

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, DatasetAlias):
            return self.name == other.name
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.name)

    def iter_dag_dependencies(self, *, source: str, target: str) -> Iterator[DagDependency]:
        """
        Iterate a dataset alias as dag dependency.

        :meta private:
        """
        yield DagDependency(
            source=source or "dataset-alias",
            target=target or "dataset-alias",
            dependency_type="dataset-alias",
            dependency_id=self.name,
        )


class DatasetAliasEvent(TypedDict):
    """A represeation of dataset event to be triggered by a dataset alias."""

    source_alias_name: str
    dest_dataset_uri: str


@attr.define()
class NoComparison(ArithmeticError):
    """Exception for when two datasets cannot be compared directly."""

    a: Dataset
    b: Dataset

    def __str__(self) -> str:
        return f"Can not compare {self.a} and {self.b}"


@attr.define()
class Dataset(os.PathLike, BaseDataset):
    """A representation of data dependencies between workflows."""

    name: str = attr.field(default=None, validator=_IdentifierValidator())
    uri: str = attr.field(
        default=None,
        kw_only=True,
        converter=_sanitize_uri,
        validator=_IdentifierValidator(),
    )
    extra: dict[str, Any] | None = attr.field(kw_only=True, default=None)

    __version__: ClassVar[int] = 1

    def __attrs_post_init__(self) -> None:
        if self.name is None and self.uri is None:
            raise TypeError("Dataset requires either name or URI")

    def __fspath__(self) -> str:
        return self.uri

    def __eq__(self, other: Any) -> bool:
        """
        Check equality of two datasets.

        Since either *name* or *uri* is required, and we ensure integrity when
        DAG files are parsed, we only need to consider the following combos:

        * Both datasets have name and uri defined: Both fields must match.
        * One dataset have only one field (name or uri) defined: The field
          defined by both must match.
        * Both datasets have the same one field defined: The field must match.
        * Either dataset has the other field defined (e.g. *self* defines only
          *name*, but *other* only *uri*): The two cannot be reliably compared,
          and (a subclass of) *ArithmeticError* is raised.

        In the last case, we can still check dataset equality by querying the
        database. We do not do here though since that has too much performance
        implication. The call site should consider the possibility instead.

        However, since *Dataset* objects created from the meta-database (e.g.
        those in the task execution context) would have both concrete name and
        URI values filled by the DAG parser. Non-comparability only happens if
        the user accesses the dataset objects that aren't created from the
        database, say globally in a DAG file. This is discouraged anyway.
        """
        if not isinstance(other, self.__class__):
            return NotImplemented
        if self.name is not None and other.name is not None:
            if self.uri is None or other.uri is None:
                return self.name == other.name
            return self.name == other.name and self.uri == other.uri
        if self.uri is not None and other.uri is not None:
            return self.uri == other.uri
        raise NoComparison(self, other)

    @property
    def normalized_uri(self) -> str | None:
        """
        Returns the normalized and AIP-60 compliant URI whenever possible.

        If we can't retrieve the scheme from URI or no normalizer is provided or if parsing fails,
        it returns None.

        If a normalizer for the scheme exists and parsing is successful we return the normalizer result.
        """
        if not (normalized_scheme := _get_normalized_scheme(self.uri)):
            return None

        if (normalizer := _get_uri_normalizer(normalized_scheme)) is None:
            return None
        parsed = urllib.parse.urlsplit(self.uri)
        try:
            normalized_uri = normalizer(parsed)
            return urllib.parse.urlunsplit(normalized_uri)
        except ValueError:
            return None

    def as_expression(self) -> Any:
        """
        Serialize the dataset into its scheduling expression.

        :meta private:
        """
        return self.uri

    def iter_datasets(self) -> Iterator[tuple[str, Dataset]]:
        yield self.uri, self

    def iter_dataset_aliases(self) -> Iterator[DatasetAlias]:
        return iter(())

    def evaluate(self, statuses: dict[str, bool]) -> bool:
        return statuses.get(self.uri, False)

    def iter_dag_dependencies(self, *, source: str, target: str) -> Iterator[DagDependency]:
        """
        Iterate a dataset as dag dependency.

        :meta private:
        """
        yield DagDependency(
            source=source or "dataset",
            target=target or "dataset",
            dependency_type="dataset",
            dependency_id=self.uri,
        )


class _DatasetBooleanCondition(BaseDataset):
    """Base class for dataset boolean logic."""

    agg_func: Callable[[Iterable], bool]

    def __init__(self, *objects: BaseDataset) -> None:
        if not all(isinstance(o, BaseDataset) for o in objects):
            raise TypeError("expect dataset expressions in condition")

        self.objects = [
            _DatasetAliasCondition(obj.name) if isinstance(obj, DatasetAlias) else obj for obj in objects
        ]

    def evaluate(self, statuses: dict[str, bool]) -> bool:
        return self.agg_func(x.evaluate(statuses=statuses) for x in self.objects)

    def iter_datasets(self) -> Iterator[tuple[str, Dataset]]:
        seen = set()  # We want to keep the first instance.
        for o in self.objects:
            for k, v in o.iter_datasets():
                if k in seen:
                    continue
                yield k, v
                seen.add(k)

    def iter_dataset_aliases(self) -> Iterator[DatasetAlias]:
        """Filter dataest aliases in the condition."""
        for o in self.objects:
            yield from o.iter_dataset_aliases()

    def iter_dag_dependencies(self, *, source: str, target: str) -> Iterator[DagDependency]:
        """
        Iterate dataset, dataset aliases and their resolved datasets  as dag dependency.

        :meta private:
        """
        for obj in self.objects:
            yield from obj.iter_dag_dependencies(source=source, target=target)


class DatasetAny(_DatasetBooleanCondition):
    """Use to combine datasets schedule references in an "and" relationship."""

    agg_func = any

    def __or__(self, other: BaseDataset) -> BaseDataset:
        if not isinstance(other, BaseDataset):
            return NotImplemented
        # Optimization: X | (Y | Z) is equivalent to X | Y | Z.
        return DatasetAny(*self.objects, other)

    def __repr__(self) -> str:
        return f"DatasetAny({', '.join(map(str, self.objects))})"

    def as_expression(self) -> dict[str, Any]:
        """
        Serialize the dataset into its scheduling expression.

        :meta private:
        """
        return {"any": [o.as_expression() for o in self.objects]}


class _DatasetAliasCondition(DatasetAny):
    """
    Use to expand DataAlias as DatasetAny of its resolved Datasets.

    :meta private:
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.objects = expand_alias_to_datasets(name)

    def __repr__(self) -> str:
        return f"_DatasetAliasCondition({', '.join(map(str, self.objects))})"

    def as_expression(self) -> Any:
        """
        Serialize the dataset into its scheduling expression.

        :meta private:
        """
        return {"alias": self.name}

    def iter_dataset_aliases(self) -> Iterator[DatasetAlias]:
        yield DatasetAlias(self.name)

    def iter_dag_dependencies(self, *, source: str = "", target: str = "") -> Iterator[DagDependency]:
        """
        Iterate a dataset alias and its resolved datasets  as dag dependency.

        :meta private:
        """
        if self.objects:
            for obj in self.objects:
                dataset = cast(Dataset, obj)
                uri = dataset.uri
                # dataset
                yield DagDependency(
                    source=f"dataset-alias:{self.name}" if source else "dataset",
                    target="dataset" if source else f"dataset-alias:{self.name}",
                    dependency_type="dataset",
                    dependency_id=uri,
                )
                # dataset alias
                yield DagDependency(
                    source=source or f"dataset:{uri}",
                    target=target or f"dataset:{uri}",
                    dependency_type="dataset-alias",
                    dependency_id=self.name,
                )
        else:
            yield DagDependency(
                source=source or "dataset-alias",
                target=target or "dataset-alias",
                dependency_type="dataset-alias",
                dependency_id=self.name,
            )


class DatasetAll(_DatasetBooleanCondition):
    """Use to combine datasets schedule references in an "or" relationship."""

    agg_func = all

    def __and__(self, other: BaseDataset) -> BaseDataset:
        if not isinstance(other, BaseDataset):
            return NotImplemented
        # Optimization: X & (Y & Z) is equivalent to X & Y & Z.
        return DatasetAll(*self.objects, other)

    def __repr__(self) -> str:
        return f"DatasetAll({', '.join(map(str, self.objects))})"

    def as_expression(self) -> Any:
        """
        Serialize the dataset into its scheduling expression.

        :meta private:
        """
        return {"all": [o.as_expression() for o in self.objects]}
