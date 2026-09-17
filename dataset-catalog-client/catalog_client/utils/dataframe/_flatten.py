"""Turn a dataset record into a flat row dict."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from catalog_client.exceptions import CatalogUsageError
from catalog_client.utils.commons import PathSegments, extract_path, parse_path
from catalog_client.utils.dataframe._columns import COMPUTED_COLUMNS, ComputedColumn
from catalog_client.utils.dataframe._types import ColumnSpec, RecordMapper

if TYPE_CHECKING:
    from catalog_client.models.dataset import (
        DatasetResponse,
        DatasetWithRelationsResponse,
    )


def _scalarize(value: Any, list_sep: str | None) -> Any:
    """Collapse an extracted value into something a dataframe cell can hold.

    Datetimes are left alone so pandas infers a datetime64 column rather than
    a column of objects.
    """
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        items = [_scalarize(item, list_sep) for item in value if item is not None]
        if list_sep is None:
            return items
        return list_sep.join(str(item) for item in items) if items else None
    return value


class RowBuilder:
    """Builds one row per dataset from a fixed column set.

    Everything a row needs that does not depend on the record — the final
    column names, each path parsed into segments, which columns are computed,
    and the set of record fields any of them read — is resolved once here
    rather than per record.  On a long walk that is the difference between
    parsing every dot-path once and parsing it once per dataset.

    A class rather than a closure over ``flatten_record``'s arguments: the
    builder outlives a single call and only needs these fields, so it should
    not keep the caller's whole frame alive.
    """

    __slots__ = ("_plan", "_include", "_mapper", "_list_sep", "_rename")

    def __init__(
        self,
        columns: Sequence[ColumnSpec],
        *,
        mapper: RecordMapper | None = None,
        list_sep: str | None = "; ",
        rename: Mapping[str, str] | None = None,
    ) -> None:
        self._mapper = mapper
        self._list_sep = list_sep
        # Only the mapper's keys still need renaming per row; the declarative
        # columns are stored under their final name below.
        self._rename = rename or None

        plan: list[tuple[str, ComputedColumn | None, PathSegments]] = []
        include: set[str] = set()
        for spec in columns:
            name = spec.column_name
            if rename:
                name = rename.get(name, name)
            computed = COMPUTED_COLUMNS.get(spec.path)
            if computed is not None:
                plan.append((name, computed, ()))
                include |= computed.sources
            else:
                segments = parse_path(spec.path)
                plan.append((name, None, segments))
                include.add(segments[0][0])
        self._plan = tuple(plan)
        self._include = include

    def build(
        self, record: DatasetResponse | DatasetWithRelationsResponse
    ) -> dict[str, Any] | None:
        """Build one row from one dataset.

        Assembly order is fixed: declarative columns, then the mapper merged
        over them, then renaming.  Returns ``None`` when the mapper drops the
        row.
        """
        # Scoped to the fields some column reads. An unscoped dump would
        # recurse into `locations` — one nested model per asset — for every
        # row, even though no default column looks at it.
        dumped = (
            record.model_dump(mode="python", include=self._include)
            if self._plan
            else {}
        )

        row: dict[str, Any] = {}
        for name, computed, segments in self._plan:
            if computed is not None:
                row[name] = computed.fn(dumped)
            else:
                row[name] = _scalarize(extract_path(dumped, segments), self._list_sep)

        if self._mapper is not None:
            try:
                mapped = self._mapper(record)
            except Exception as exc:
                # Without the id, an AttributeError from a sparse record
                # part-way through a walk gives no clue which dataset
                # triggered it — and every metadata submodel is optional, so
                # that is the likely fault.
                raise CatalogUsageError(
                    f"mapper raised {type(exc).__name__} on dataset "
                    f"{getattr(record, 'id', '<unknown>')!r}: {exc}"
                ) from exc
            if mapped is None:
                return None
            # Mapper values are passed through as-is: the caller built them
            # deliberately, so no list joining and no enum unwrapping.
            if self._rename:
                rename = self._rename
                row.update(
                    (rename.get(key, key), value) for key, value in mapped.items()
                )
            else:
                row.update(mapped)

        return row


def flatten_record(
    record: DatasetResponse | DatasetWithRelationsResponse,
    columns: Sequence[ColumnSpec],
    *,
    mapper: RecordMapper | None = None,
    list_sep: str | None = "; ",
    rename: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Build one row from one dataset, resolving the columns on every call.

    The one-shot form of :class:`RowBuilder`.  A walk should build the builder
    once and call :meth:`RowBuilder.build` per record instead.
    """
    return RowBuilder(columns, mapper=mapper, list_sep=list_sep, rename=rename).build(
        record
    )
