"""Public types for the manifest package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, overload


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
        return self.path.removeprefix("metadata.")

    @property
    def column_name(self) -> str:
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

    @overload
    def __getitem__(self, index: int) -> dict[str, Any]: ...
    @overload
    def __getitem__(self, index: slice) -> list[dict[str, Any]]: ...
    def __getitem__(self, index: int | slice) -> dict[str, Any] | list[dict[str, Any]]:
        return self.rows[index]
