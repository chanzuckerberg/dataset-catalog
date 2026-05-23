"""Generate a flat JSON manifest from a collection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from catalog_client.client.catalog import CatalogClient


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


def _asset_matches(asset: dict[str, Any], filter_condition: dict[str, Any]) -> bool:
    """Return True if the asset satisfies every condition (AND logic).

    Each value in *filter_condition* may be:

    * **scalar** — equality match
    * **list** — any-of match (asset value must be in the list)
    * **dict** — operator match; supported operators:
      ``startswith``, ``endswith``, ``contains``,
      ``gt``, ``gte``, ``lt``, ``lte``
    """
    for field, condition in filter_condition.items():
        value = asset.get(field)

        if isinstance(condition, dict):
            for op, operand in condition.items():
                if op == "startswith":
                    if not (isinstance(value, str) and value.startswith(operand)):
                        return False
                elif op == "endswith":
                    if not (isinstance(value, str) and value.endswith(operand)):
                        return False
                elif op == "contains":
                    if not (isinstance(value, str) and operand in value):
                        return False
                elif op == "gt":
                    if value is None or value <= operand:
                        return False
                elif op == "gte":
                    if value is None or value < operand:
                        return False
                elif op == "lt":
                    if value is None or value >= operand:
                        return False
                elif op == "lte":
                    if value is None or value > operand:
                        return False
                else:
                    raise ValueError(f"Unknown filter operator: {op!r}")
        elif isinstance(condition, list):
            if value not in condition:
                return False
        else:
            if value != condition:
                return False

    return True


def generate_manifest(
    client: CatalogClient,
    collection_id: str,
    *,
    metadata_fields: list[str] | None = None,
    filter_condition: dict[str, Any] | None = None,
    exclude_tombstoned: bool = True,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Generate a flat manifest of assets from every dataset in a collection.

    Each entry corresponds to one data asset (location) from a dataset.
    Datasets with multiple locations produce multiple entries, each sharing
    the same dataset-level fields.

    Args:
        client: An authenticated :class:`CatalogClient`.
        collection_id: UUID of the collection to generate the manifest for.
        metadata_fields: Dot-notation paths to extract from each dataset's
            metadata, e.g. ``["sample.organism[].label",
            "experiment.sub_modality"]``.  Missing paths resolve to ``None``.
        filter_condition: Dict of asset field constraints.  Values may be a
            scalar (equality), a list (any-of), or a dict of operators
            (``startswith``, ``endswith``, ``contains``,
            ``gt``, ``gte``, ``lt``, ``lte``).
        exclude_tombstoned: Skip tombstoned datasets and assets (default
            ``True``).
        page_size: Entries to fetch per API page (capped at 100).

    Returns:
        List of dicts, one per matching asset, with fixed keys
        ``dataset_id``, ``canonical_id``, ``version``, ``record_version``,
        ``location_uri``, ``storage_platform``, ``checksum``,
        ``checksum_alg``, plus one key per requested *metadata_fields* path.
    """
    entries: list[dict[str, Any]] = []
    offset = 0

    while True:
        page = client.collections.list_entries(
            collection_id, offset=offset, limit=page_size
        )

        for entry in page.results:
            if entry.entry_type != "dataset":
                continue

            dataset = entry.entry
            if exclude_tombstoned and dataset.tombstoned:
                continue

            metadata_dict = dataset.metadata.model_dump() if dataset.metadata else {}

            dataset_fields: dict[str, Any] = {
                "dataset_id": dataset.id,
                "canonical_id": dataset.canonical_id,
                "version": dataset.version,
                "record_version": dataset.record_version,
            }

            clean_metadata_fields = [
                field_path.removeprefix("metadata.")
                for field_path in (metadata_fields or [])
            ]

            extracted: dict[str, Any] = {
                field_path: _extract_metadata_field(metadata_dict, field_path)
                for field_path in clean_metadata_fields
            }

            for asset in dataset.locations:
                if exclude_tombstoned and asset.tombstoned:
                    continue

                asset_dict = asset.model_dump(mode="json")

                if filter_condition and not _asset_matches(
                    asset_dict, filter_condition
                ):
                    continue

                entries.append(
                    {
                        **dataset_fields,
                        "location_uri": asset.location_uri,
                        "storage_platform": asset_dict.get("storage_platform"),
                        "checksum": asset.checksum,
                        "checksum_alg": asset.checksum_alg,
                        **extracted,
                    }
                )

        offset += page_size
        if offset >= page.total:
            break

    return entries
