"""Turn a dataset record into a flat row dict."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Any, Mapping

from catalog_client.exceptions import CatalogUsageError
from catalog_client.utils._extract import _extract_metadata_field
from catalog_client.utils.dataframe._columns import COMPUTED_COLUMNS
from catalog_client.utils.dataframe._types import ColumnSpec, RecordMapper

if TYPE_CHECKING:
    from catalog_client.models.dataset import (
        DatasetResponse,
        DatasetWithRelationsResponse,
    )


def _scalarize(value: Any, list_sep: str | None) -> Any:
    """Collapse a extracted value into something a dataframe cell can hold.

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


def flatten_record(
    record: DatasetResponse | DatasetWithRelationsResponse,
    columns: list[ColumnSpec],
    *,
    mapper: RecordMapper | None = None,
    list_sep: str | None = "; ",
    rename: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Build one row from one dataset.

    Assembly order is fixed: declarative *columns*, then the *mapper* merged
    over them, then *rename*.  Returns ``None`` when the mapper drops the row.
    """
    dumped = record.model_dump(mode="python")

    row: dict[str, Any] = {}
    for column in columns:
        computed = COMPUTED_COLUMNS.get(column.path)
        if computed is not None:
            row[column.column_name] = computed(dumped)
        else:
            raw = _extract_metadata_field(dumped, column.path)
            row[column.column_name] = _scalarize(raw, list_sep)

    if mapper is not None:
        try:
            mapped = mapper(record)
        except Exception as exc:
            # Without the id, an AttributeError from a sparse record part-way
            # through a walk gives no clue which dataset triggered it — and
            # every metadata submodel is optional, so that is the likely fault.
            raise CatalogUsageError(
                f"mapper raised {type(exc).__name__} on dataset "
                f"{getattr(record, 'id', '<unknown>')!r}: {exc}"
            ) from exc
        if mapped is None:
            return None
        # Mapper values are passed through as-is: the caller built them
        # deliberately, so no list joining and no enum unwrapping.
        row.update(mapped)

    if rename:
        row = {rename.get(key, key): value for key, value in row.items()}

    return row
