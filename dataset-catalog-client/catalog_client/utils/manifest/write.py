"""Manifest output writers — CSV and JSON."""

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Literal, get_args

from catalog_client.utils.manifest._types import ManifestResult

ManifestFormat = Literal["csv", "json"]

_SUPPORTED_FORMATS: frozenset[str] = frozenset(get_args(ManifestFormat))


def write_manifest(
    rows: ManifestResult | Iterable[dict[str, Any]],
    path: str | Path,
    *,
    format: ManifestFormat = "csv",
) -> None:
    """Write manifest rows to a file.

    Args:
        rows: A :class:`ManifestResult` or any iterable of row dicts.
        path: Destination file path.
        format: Output format.  Supported values:

            - ``"csv"`` *(default)* — UTF-8 CSV with a header row.
            - ``"json"`` — JSON array of objects, pretty-printed.

    Raises:
        ValueError: If *format* is not a supported value.
        ValueError: If *rows* is empty — nothing would be written.

    Examples::

        from catalog_client.utils.manifest import generate_manifest, write_manifest

        result = generate_manifest(client, collection_id, metadata_fields=[...])
        write_manifest(result, "manifest.csv")
        write_manifest(result, "manifest.json", format="json")
    """
    if format not in _SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format {format!r}. Supported: {_SUPPORTED_FORMATS}"
        )

    row_list: list[dict[str, Any]] = (
        rows.rows if isinstance(rows, ManifestResult) else list(rows)
    )

    if not row_list:
        raise ValueError("No rows to write — manifest is empty.")

    dest = Path(path)

    if format == "csv":
        _write_csv(row_list, dest)
    elif format == "json":
        _write_json(row_list, dest)


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def _write_json(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, default=str)
