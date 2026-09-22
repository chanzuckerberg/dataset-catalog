"""Public types for the dataframe package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping

if TYPE_CHECKING:
    from catalog_client.models.dataset import (
        DatasetResponse,
        DatasetWithRelationsResponse,
    )


@dataclass(frozen=True)
class ColumnSpec:
    """A column to include in the output frame.

    Args:
        path: Dot-notation path into the dataset record.  Unlike
            :class:`~catalog_client.utils.manifest.MetadataFieldSpec`, this is
            rooted at the dataset itself, so metadata paths carry the
            ``metadata.`` prefix.  Use a ``[]`` suffix on a segment to expand a
            list value, or an integer segment to index into one.
        alias: Column name in the output.  Defaults to *path* when not given.

    Examples::

        ColumnSpec("canonical_id")
        ColumnSpec("governance.license", alias="license")
        ColumnSpec("metadata.sample.organism[].label", alias="organism")
    """

    path: str
    alias: str | None = None

    @property
    def column_name(self) -> str:
        return self.alias if self.alias is not None else self.path


RecordMapper = Callable[
    ["DatasetResponse | DatasetWithRelationsResponse"],
    "Mapping[str, Any] | None",
]
"""Turn a dataset record into a row.

Receives the Pydantic model, not a dict, so metadata can be reached by typed
attribute access.  The returned mapping is merged *over* the columns extracted
declaratively, so it can add or override.  Return ``None`` to drop the row.

Which model arrives depends on the route the filters select, so a mapper must
not assume the ``DatasetWithRelationsResponse`` fields are populated.
"""
