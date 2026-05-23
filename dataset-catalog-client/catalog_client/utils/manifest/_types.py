"""Public types for the manifest package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, TypedDict


class FieldFilter(TypedDict, total=False):
    """Operator dict for a single asset field.

    All present operators must pass (AND logic).  Supported operators:

    - Equality: ``eq_`` (str or numeric)
    - Membership: ``in_`` (value in list), ``nin_`` (value not in list)
    - String: ``startswith_``, ``endswith_``, ``contains_``
    - Numeric / comparable: ``gt_``, ``gte_``, ``lt_``, ``lte_``

    Examples::

        {"location_uri": {"endswith_": ".tiff"}}
        {"storage_platform": {"in_": ["s3", "gcs"]}}
        {"asset_type": {"nin_": ["folder"]}}
        {"record_version": {"eq_": 1}}
    """

    eq_: Any
    in_: list[Any]
    nin_: list[Any]
    startswith_: str
    endswith_: str
    contains_: str
    gt_: Any
    gte_: Any
    lt_: Any
    lte_: Any


FilterCondition = dict[str, FieldFilter]
"""Maps asset field names to :class:`FieldFilter` operator dicts (all must pass — AND logic).

Example::

    {
        "asset_type": {"eq_": "file"},
        "storage_platform": {"in_": ["s3", "gcs"]},
        "location_uri": {"endswith_": ".tiff"},
        "record_version": {"gte_": 2},
    }
"""


@dataclass
class MetadataFieldSpec:
    """A metadata field to include in each manifest row.

    Args:
        path: Dot-notation path into the dataset metadata.  Use a ``[]``
            suffix on a segment to expand a list value.
        alias: Column name in the manifest output.  Defaults to *path*
            (with any ``metadata.`` prefix stripped) when not provided.

    Examples::

        MetadataFieldSpec("experiment.sub_modality")
        MetadataFieldSpec("experiment.sub_modality", alias="modality")
        MetadataFieldSpec("sample.organism[].label", alias="organisms")
    """

    path: str
    alias: str | None = None

    @property
    def clean_path(self) -> str:
        """Path with any ``metadata.`` prefix stripped."""
        return self.path.removeprefix("metadata.")

    @property
    def column_name(self) -> str:
        """Output column name: :attr:`alias` if set, otherwise :attr:`clean_path`."""
        return self.alias if self.alias is not None else self.clean_path


@dataclass
class ManifestStats:
    """Summary counters produced by :func:`~catalog_client.utils.manifest.generate_manifest`."""

    total_datasets: int = 0
    """Datasets visited (tombstoned datasets are included in this count)."""
    skipped_tombstoned_datasets: int = 0
    """Datasets skipped because they were tombstoned."""
    skipped_tombstoned_assets: int = 0
    """Asset locations skipped because they were tombstoned."""
    skipped_filtered_assets: int = 0
    """Asset locations skipped because they did not match *filter_condition*."""
    total_rows: int = 0
    """Rows emitted into the manifest."""


@dataclass
class ManifestResult:
    """Return value of :func:`~catalog_client.utils.manifest.generate_manifest`.

    Supports list-like access (``bool``, ``len``, iteration, indexing) so that
    existing code expecting a ``list[dict]`` continues to work.  New code
    should prefer accessing :attr:`rows` and :attr:`stats` directly.
    """

    rows: list[dict[str, Any]]
    stats: ManifestStats

    def __bool__(self) -> bool:
        return bool(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.rows)

    def __getitem__(self, index: int | slice) -> dict[str, Any] | list[dict[str, Any]]:
        return self.rows[index]
