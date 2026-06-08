"""Public manifest generation functions."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Callable, Iterator

if TYPE_CHECKING:
    from catalog_client.client.catalog import CatalogClient

from catalog_client.utils.manifest._filter import FilterCondition
from catalog_client.utils.manifest._iterator import _iter_entries
from catalog_client.utils.manifest._types import (
    ManifestResult,
    ManifestStats,
    MetadataFieldSpec,
)

_MAX_PAGE_SIZE = 100


def _validate_page_size(page_size: int) -> int:
    """Cap page_size at the API maximum, warning if exceeded."""
    if page_size > _MAX_PAGE_SIZE:
        warnings.warn(
            f"page_size={page_size} exceeds the API maximum of {_MAX_PAGE_SIZE}; "
            f"capping at {_MAX_PAGE_SIZE}.",
            UserWarning,
            stacklevel=3,
        )
        return _MAX_PAGE_SIZE
    return page_size


def generate_manifest_iter(
    client: CatalogClient,
    collection_id: str,
    *,
    metadata_fields: list[MetadataFieldSpec] | None = None,
    filter_condition: FilterCondition | None = None,
    exclude_tombstoned: bool = True,
    page_size: int = _MAX_PAGE_SIZE,
    recurse: bool = False,
    on_progress: Callable[[int], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield one dict per matching asset, streaming results page by page.

    Useful for large collections where you want to process rows as they arrive
    or drive a progress bar without buffering the entire manifest in memory.

    Args:
        client: An authenticated :class:`~catalog_client.CatalogClient`.
        collection_id: UUID of the collection to stream.
        metadata_fields: Fields to extract from dataset metadata.  Each item
            is a :class:`~catalog_client.utils.manifest.MetadataFieldSpec` with
            a required ``path`` and an optional ``alias`` for the output column
            name.
        filter_condition: Asset-level filter; rows that do not match are
            silently skipped.  See :data:`~catalog_client.utils.manifest.FilterCondition`.
        exclude_tombstoned: Skip tombstoned datasets and assets (default
            ``True``).
        page_size: Entries fetched per API request.  Capped at 100 by the API;
            a warning is issued if a higher value is passed.
        recurse: When ``True``, recurse into child collections.  Cycle
            detection prevents infinite loops.
        on_progress: Optional callback ``on_progress(datasets_processed)``
            called after each dataset is visited (whether or not it produced
            rows).  In recursive mode the count is per-collection.

    Yields:
        One ``dict`` per matching asset.  Fixed keys: ``dataset_id``,
        ``canonical_id``, ``version``, ``record_version``, ``location_uri``,
        ``storage_platform``, ``checksum``, ``checksum_alg``, plus one key
        per :class:`~catalog_client.utils.manifest.MetadataFieldSpec` in
        *metadata_fields* (keyed by
        :attr:`~catalog_client.utils.manifest.MetadataFieldSpec.column_name`).
    """
    page_size = _validate_page_size(page_size)
    parsed_fields = [(f.clean_path, f.column_name) for f in (metadata_fields or [])]
    yield from _iter_entries(
        client,
        collection_id,
        parsed_fields,
        filter_condition,
        exclude_tombstoned,
        page_size,
        recurse,
        on_progress,
        stats=None,
    )


def generate_manifest(
    client: CatalogClient,
    collection_id: str,
    *,
    metadata_fields: list[MetadataFieldSpec] | None = None,
    filter_condition: FilterCondition | None = None,
    exclude_tombstoned: bool = True,
    page_size: int = _MAX_PAGE_SIZE,
    recurse: bool = False,
    on_progress: Callable[[int], None] | None = None,
) -> ManifestResult:
    """Generate a flat manifest of assets from every dataset in a collection.

    Returns a :class:`ManifestResult` containing all rows and a
    :class:`ManifestStats` summary.  The result supports list-like access for
    backwards compatibility with code expecting a plain ``list[dict]``.

    For large collections, prefer :func:`generate_manifest_iter` to stream
    rows page by page without buffering everything in memory.

    Args:
        client: An authenticated :class:`~catalog_client.CatalogClient`.
        collection_id: UUID of the collection to generate the manifest for.
        metadata_fields: Fields to extract from dataset metadata.  Each item
            is a :class:`~catalog_client.utils.manifest.MetadataFieldSpec` with
            a required ``path`` and an optional ``alias`` for the output column
            name.  A :class:`UserWarning` is issued for any field whose path
            resolves to ``None`` for every row — usually indicating a path typo.
        filter_condition: Asset-level filter.  See
            :data:`~catalog_client.utils.manifest.FilterCondition`.
        exclude_tombstoned: Skip tombstoned datasets and assets (default
            ``True``).
        page_size: Entries fetched per API request.  Capped at 100 by the API;
            a warning is issued if a higher value is passed.
        recurse: When ``True``, recurse into child collections.
        on_progress: Optional callback ``on_progress(datasets_processed)``
            called after each dataset is visited.

    Returns:
        :class:`ManifestResult` with :attr:`~ManifestResult.rows` and
        :attr:`~ManifestResult.stats`.
    """
    page_size = _validate_page_size(page_size)
    parsed_fields = [(f.clean_path, f.column_name) for f in (metadata_fields or [])]
    stats = ManifestStats()
    rows = list(
        _iter_entries(
            client,
            collection_id,
            parsed_fields,
            filter_condition,
            exclude_tombstoned,
            page_size,
            recurse,
            on_progress,
            stats=stats,
        )
    )

    if rows and parsed_fields:
        for path, alias in parsed_fields:
            if all(row.get(alias) is None for row in rows):
                warnings.warn(
                    f"Metadata field {path!r} (column {alias!r}) resolved to None "
                    f"for all {len(rows)} rows. "
                    "Verify the path syntax and metadata schema.",
                    UserWarning,
                    stacklevel=2,
                )

    return ManifestResult(rows=rows, stats=stats)
