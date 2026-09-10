"""Default column set and the computed-column registry."""

from __future__ import annotations

import collections.abc
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from catalog_client.exceptions import CatalogUsageError
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


@dataclass(frozen=True)
class ComputedColumn:
    """A column produced by a function instead of a dot-path.

    Args:
        fn: Called with the dumped record, returns the cell value.
        sources: Top-level record fields *fn* reads.  Declared so the flatten
            step can scope its ``model_dump`` to the fields some column
            actually needs — dumping ``locations`` costs one nested model per
            asset, which is the bulk of the work on an asset-heavy dataset.
    """

    fn: Callable[[dict[str, Any]], Any]
    sources: frozenset[str]


COMPUTED_COLUMNS: dict[str, ComputedColumn] = {
    "asset_count": ComputedColumn(
        lambda record: len(record.get("locations") or []),
        frozenset({"locations"}),
    ),
    "total_size_bytes": ComputedColumn(
        _total_size_bytes,
        frozenset({"locations"}),
    ),
}
"""Column names resolved by a function rather than a dot-path.

These summarize ``locations`` so that asking for asset information does not
multiply rows.  For one row per asset, use
:func:`~catalog_client.utils.manifest.generate_manifest` instead.
"""


def output_names(
    specs: Sequence[ColumnSpec],
    rename: Mapping[str, str] | None,
) -> list[str]:
    """Final column names for *specs*, after *rename* is applied.

    The one place the ``column_name``-then-``rename`` rule is spelled out, so
    the row builder, the empty-frame schema, and the empty-column warning
    cannot disagree about what a column ends up called.
    """
    if not rename:
        return [spec.column_name for spec in specs]
    return [rename.get(spec.column_name, spec.column_name) for spec in specs]


def resolve_columns(
    columns: Sequence[str | ColumnSpec] | None,
) -> list[ColumnSpec]:
    """Normalize the *columns* argument into a list of ColumnSpec.

    ``None`` selects :data:`DEFAULT_COLUMNS`; an empty sequence selects no
    declarative columns at all, which is how a mapper-only frame is requested.

    Raises:
        CatalogUsageError: If *columns* is a bare string, is not a sequence at
            all, or contains an entry that is neither a ``str`` nor a
            :class:`ColumnSpec`.  A ``str`` satisfies ``Sequence[str]``, so the
            annotation alone does not rule the first case out and it would
            otherwise iterate per character into one column per letter.
    """
    if columns is None:
        return list(DEFAULT_COLUMNS)
    if isinstance(columns, str):
        raise CatalogUsageError(
            f"columns must be a sequence of paths, not the bare string "
            f"{columns!r}. Pass [{columns!r}] for a single column."
        )
    if not isinstance(columns, collections.abc.Sequence):
        # Catches a dict (which would resolve to its keys) and a one-shot
        # iterator, which to_dataframe would exhaust here and then find empty
        # when it re-resolves the names for a zero-row frame.
        raise CatalogUsageError(
            f"columns must be a list or tuple, got {type(columns).__name__}. "
            "A generator cannot be used because the names are read more than "
            "once; materialize it first."
        )

    resolved = []
    for position, column in enumerate(columns):
        if isinstance(column, ColumnSpec):
            resolved.append(column)
        elif isinstance(column, str):
            resolved.append(ColumnSpec(column))
        else:
            # Coercing with str() here would turn 1 into a column named "1"
            # and None into one named "None" — a silently wrong frame rather
            # than a rejected argument.
            raise CatalogUsageError(
                f"columns[{position}] must be a dot-path string or a "
                f"ColumnSpec, got {type(column).__name__} {column!r}."
            )
    return resolved
