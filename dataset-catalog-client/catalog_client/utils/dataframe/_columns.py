"""Default column set and the computed-column registry."""

from __future__ import annotations

from typing import Any, Callable

from catalog_client.utils.dataframe._types import ColumnSpec

DEFAULT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("id"),
    ColumnSpec("canonical_id"),
    ColumnSpec("version"),
    ColumnSpec("name"),
    ColumnSpec("project"),
    ColumnSpec("modality"),
    ColumnSpec("dataset_type"),
    ColumnSpec("is_latest"),
    ColumnSpec("metadata.sample.organism[].label", alias="organism"),
    ColumnSpec("metadata.sample.tissue[].label", alias="tissue"),
    ColumnSpec("metadata.sample.disease[].label", alias="disease"),
    ColumnSpec("metadata.experiment.sub_modality", alias="sub_modality"),
    ColumnSpec("governance.access_scope", alias="access_scope"),
    ColumnSpec("governance.license", alias="license"),
    ColumnSpec("created_at"),
    ColumnSpec("last_modified_at"),
)
"""Columns used when *columns* is not supplied.

Dataset metadata only — nothing derived from ``locations``.  Ask for
``asset_count`` or ``total_size_bytes`` explicitly if you want them::

    to_dataframe(client, columns=[*DEFAULT_COLUMNS, "asset_count"])
"""


def _total_size_bytes(record: dict[str, Any]) -> int | None:
    """Sum ``size_bytes`` across a record's locations, or None if none report one.

    None rather than 0 when nothing reports a size, so "no size information"
    stays distinguishable from "genuinely empty".
    """
    total: int | None = None
    for location in record.get("locations") or []:
        if not isinstance(location, dict):
            continue
        size = location.get("size_bytes")
        if size is None:
            continue
        total = size if total is None else total + size
    return total


COMPUTED_COLUMNS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "asset_count": lambda record: len(record.get("locations") or []),
    "total_size_bytes": _total_size_bytes,
}
"""Column names resolved by a function rather than a dot-path.

These summarize ``locations`` so that asking for asset information does not
multiply rows.  For one row per asset, use
:func:`~catalog_client.utils.manifest.generate_manifest` instead.
"""


def resolve_columns(
    columns: object,
) -> list[ColumnSpec]:
    """Normalize the *columns* argument into a list of ColumnSpec.

    ``None`` selects :data:`DEFAULT_COLUMNS`; an empty sequence selects no
    declarative columns at all, which is how a mapper-only frame is requested.
    """
    if columns is None:
        return list(DEFAULT_COLUMNS)
    return [
        column if isinstance(column, ColumnSpec) else ColumnSpec(str(column))
        for column in columns  # type: ignore[attr-defined]
    ]
