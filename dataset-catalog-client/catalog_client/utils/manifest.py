"""Generate a flat JSON manifest from a collection."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterator, TypedDict

if TYPE_CHECKING:
    from catalog_client.client.catalog import CatalogClient

_MAX_PAGE_SIZE = 100


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


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
    """Summary counters produced by :func:`generate_manifest`."""

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
    """Return value of :func:`generate_manifest`.

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_metadata_field(metadata: dict[str, Any], path: str) -> Any:
    """Extract a value from a metadata dict using dot-notation with list expansion.

    A segment ending with ``[]`` signals that the value at that key is a list;
    the remaining path is applied to each item and the results are returned as a
    list.  Any missing intermediate key returns ``None`` without raising.

    Examples::

        # metadata = {"sample": {"organism": [{"label": "Homo sapiens"}]}}
        _extract_metadata_field(metadata, "sample.organism[].label")
        # → ["Homo sapiens"]

        _extract_metadata_field(metadata, "experiment.sub_modality")
        # → "confocal"  (or None if absent)
    """
    segments = path.split(".")
    current: Any = metadata

    for i, segment in enumerate(segments):
        if current is None:
            return None

        is_list_expand = segment.endswith("[]")
        key = segment[:-2] if is_list_expand else segment

        if not isinstance(current, dict):
            return None
        current = current.get(key)

        if is_list_expand:
            if not isinstance(current, list):
                return None
            remaining = ".".join(segments[i + 1 :])
            if not remaining:
                return current
            return [
                _extract_metadata_field(item, remaining)
                if isinstance(item, dict)
                else None
                for item in current
            ]

    return current


def _asset_matches(asset: dict[str, Any], filter_condition: FilterCondition) -> bool:
    """Return True if the asset satisfies every :class:`FieldFilter` (AND logic)."""
    for field, operators in filter_condition.items():
        value = asset.get(field)

        op: str
        operand: Any
        for op, operand in operators.items():
            if op == "eq_":
                if value != operand:
                    return False
            elif op == "in_":
                if value not in operand:
                    return False
            elif op == "nin_":
                if value in operand:
                    return False
            elif op == "startswith_":
                if not (isinstance(value, str) and value.startswith(operand)):
                    return False
            elif op == "endswith_":
                if not (isinstance(value, str) and value.endswith(operand)):
                    return False
            elif op == "contains_":
                if not (isinstance(value, str) and operand in value):
                    return False
            elif op == "gt_":
                if value is None or value <= operand:
                    return False
            elif op == "gte_":
                if value is None or value < operand:
                    return False
            elif op == "lt_":
                if value is None or value >= operand:
                    return False
            elif op == "lte_":
                if value is None or value > operand:
                    return False
            else:
                raise ValueError(f"Unknown filter operator: {op!r}")

    return True


def _iter_entries(
    client: CatalogClient,
    collection_id: str,
    parsed_fields: list[tuple[str, str]],
    filter_condition: FilterCondition | None,
    exclude_tombstoned: bool,
    page_size: int,
    recurse: bool,
    on_progress: Callable[[int], None] | None,
    _visited: set[str],
    stats: ManifestStats | None,
) -> Iterator[dict[str, Any]]:
    """Core generator — yields one row per matching asset.

    Shared by both :func:`generate_manifest_iter` and :func:`generate_manifest`.
    When *stats* is provided it is mutated with running counters.
    """
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
                            _visited,
                            stats,
                        )
                continue

            # entry_type == "dataset"
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
                asset_dict = asset.model_dump(mode="json")

                if exclude_tombstoned and asset.tombstoned:
                    if stats is not None:
                        stats.skipped_tombstoned_assets += 1
                    continue

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
                    "location_uri": asset.location_uri,
                    "storage_platform": asset_dict.get("storage_platform"),
                    "checksum": asset.checksum,
                    "checksum_alg": asset.checksum_alg,
                    **extracted,
                }

            if on_progress is not None:
                on_progress(datasets_processed)

        offset += page_size
        if offset >= page.total:
            break


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_manifest_iter(
    client: CatalogClient,
    collection_id: str,
    *,
    metadata_fields: list[MetadataFieldSpec] | None = None,
    filter_condition: FilterCondition | None = None,
    exclude_tombstoned: bool = True,
    page_size: int = 100,
    recurse: bool = False,
    on_progress: Callable[[int], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield one dict per matching asset, streaming results page by page.

    Useful for large collections where you want to process rows as they arrive
    or drive a progress bar without buffering the entire manifest in memory.

    Args:
        client: An authenticated :class:`CatalogClient`.
        collection_id: UUID of the collection to stream.
        metadata_fields: Fields to extract from dataset metadata.  Each item
            is a :class:`MetadataFieldSpec` with a required ``path`` and an
            optional ``alias`` for the output column name.
        filter_condition: Asset-level filter; rows that do not match are
            silently skipped.  See :data:`FilterCondition`.
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
        per :class:`MetadataFieldSpec` in *metadata_fields* (keyed by
        :attr:`~MetadataFieldSpec.column_name`).
    """
    if page_size > _MAX_PAGE_SIZE:
        warnings.warn(
            f"page_size={page_size} exceeds the API maximum of {_MAX_PAGE_SIZE}; "
            f"capping at {_MAX_PAGE_SIZE}.",
            UserWarning,
            stacklevel=2,
        )
        page_size = _MAX_PAGE_SIZE

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
        _visited={collection_id},
        stats=None,
    )


def generate_manifest(
    client: CatalogClient,
    collection_id: str,
    *,
    metadata_fields: list[MetadataFieldSpec] | None = None,
    filter_condition: FilterCondition | None = None,
    exclude_tombstoned: bool = True,
    page_size: int = 100,
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
        client: An authenticated :class:`CatalogClient`.
        collection_id: UUID of the collection to generate the manifest for.
        metadata_fields: Fields to extract from dataset metadata.  Each item
            is a :class:`MetadataFieldSpec` with a required ``path`` and an
            optional ``alias`` for the output column name.  A
            :class:`UserWarning` is issued for any field whose path resolves
            to ``None`` for every row — usually indicating a path typo.
        filter_condition: Asset-level filter.  See :data:`FilterCondition`.
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
    if page_size > _MAX_PAGE_SIZE:
        warnings.warn(
            f"page_size={page_size} exceeds the API maximum of {_MAX_PAGE_SIZE}; "
            f"capping at {_MAX_PAGE_SIZE}.",
            UserWarning,
            stacklevel=2,
        )
        page_size = _MAX_PAGE_SIZE

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
            _visited={collection_id},
            stats=stats,
        )
    )

    # Warn on field paths that resolved to None for every row — likely a typo.
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
