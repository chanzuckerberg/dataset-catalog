"""Core pagination and recursion generator for manifest entry traversal."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Iterator

if TYPE_CHECKING:
    from catalog_client.client.catalog import CatalogClient

from catalog_client.utils.manifest._extractor import _extract_metadata_field
from catalog_client.utils.manifest._filter import FilterCondition, _asset_matches
from catalog_client.utils.manifest._types import ManifestStats


def _iter_entries(
    client: CatalogClient,
    collection_id: str,
    parsed_fields: list[tuple[str, str]],
    filter_condition: FilterCondition | None,
    exclude_tombstoned: bool,
    page_size: int,
    recurse: bool,
    on_progress: Callable[[int], None] | None,
    stats: ManifestStats | None,
    _visited: set[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Core generator — yields one row per matching asset.

    When *stats* is provided it is mutated with running counters.

    *_visited* tracks collection IDs already processed to prevent cycles during
    recursive traversal.  Callers should leave it unset; it is managed internally.
    """
    if _visited is None:
        _visited = {collection_id}
    offset = 0
    datasets_processed = 0

    while True:
        page = client.collections.list_entries(
            collection_id, offset=offset, limit=page_size
        )

        for entry in page.results:
            if entry.entry_type == "collection":
                if recurse:
                    child_id = entry.entry.id
                    if child_id not in _visited:
                        _visited.add(child_id)
                        yield from _iter_entries(
                            client,
                            child_id,
                            parsed_fields,
                            filter_condition,
                            exclude_tombstoned,
                            page_size,
                            recurse,
                            on_progress,
                            stats,
                            _visited,
                        )
                continue

            dataset = entry.entry
            datasets_processed += 1
            if stats is not None:
                stats.total_datasets += 1

            if exclude_tombstoned and dataset.tombstoned:
                if stats is not None:
                    stats.skipped_tombstoned_datasets += 1
                if on_progress is not None:
                    on_progress(datasets_processed)
                continue

            metadata_dict = dataset.metadata.model_dump() if dataset.metadata else {}

            dataset_fields: dict[str, Any] = {
                "dataset_id": dataset.id,
                "canonical_id": dataset.canonical_id,
                "version": dataset.version,
                "record_version": dataset.record_version,
            }

            extracted = {
                alias: _extract_metadata_field(metadata_dict, path)
                for path, alias in parsed_fields
            }

            for asset in dataset.locations:
                if exclude_tombstoned and asset.tombstoned:
                    if stats is not None:
                        stats.skipped_tombstoned_assets += 1
                    continue

                # Serialize once: needed for filter evaluation and for
                # storage_platform (enum → string) in the output row.
                asset_dict = asset.model_dump(mode="json")

                if filter_condition and not _asset_matches(
                    asset_dict, filter_condition
                ):
                    if stats is not None:
                        stats.skipped_filtered_assets += 1
                    continue

                if stats is not None:
                    stats.total_rows += 1

                yield {
                    **dataset_fields,
                    "location_uri": asset_dict["location_uri"],
                    "storage_platform": asset_dict.get("storage_platform"),
                    "checksum": asset_dict.get("checksum"),
                    "checksum_alg": asset_dict.get("checksum_alg"),
                    **extracted,
                }

            if on_progress is not None:
                on_progress(datasets_processed)

        offset += page_size
        if offset >= page.total:
            break
