#!/usr/bin/env python3
"""Filter a catalog's data assets by their description (and format / type).

The catalog API has **no asset-level search endpoint** — data assets
(``locations``) are only ever returned embedded inside a dataset record. So
"find assets whose description mentions X" is necessarily a *client-side* pass:
this script lists datasets (optionally narrowed by project / modality / etc.),
flattens their ``locations``, and keeps only the assets whose fields match.

Because it walks whole dataset records, always narrow the scan with dataset
filters first (``--project`` / ``--modality`` / ``--canonical-id``). ``--scan-limit``
caps how many datasets are fetched and WARNS on stderr when more matched, so a
truncated scan never reads as a complete one.

Configuration comes from the environment (same as the ``catalog`` CLI):
    CATALOG_API_URL    base URL of the catalog
    CATALOG_API_TOKEN  API token (issue at <catalog>/docs -> /token/issue)

Examples:
    # assets whose description mentions "segmentation mask", within one project
    python filter_assets.py --description "segmentation mask" --project CellXGene

    # OME-TIFF assets across imaging datasets, as JSON
    python filter_assets.py --file-format tiff --modality imaging -o json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Iterator, NoReturn

from catalog_client.client.catalog import CatalogClient
from catalog_client.exceptions import CatalogError
from catalog_client.models.asset import AssetType
from catalog_client.models.dataset import DatasetModality

EXIT_USAGE = 2


def _usage_error(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(EXIT_USAGE)


def _client() -> CatalogClient:
    url = os.environ.get("CATALOG_API_URL")
    token = os.environ.get("CATALOG_API_TOKEN")
    if not url or not token:
        _usage_error("set CATALOG_API_URL and CATALOG_API_TOKEN in the environment.")
    return CatalogClient(base_url=url, api_token=token)


def _modality(value: str | None) -> DatasetModality | None:
    if value is None:
        return None
    try:
        return DatasetModality(value)
    except ValueError:
        members = ", ".join(m.value for m in DatasetModality)
        _usage_error(f"invalid --modality {value!r}; expected one of: {members}")


def _iter_datasets(client: CatalogClient, scan_limit: int, **filters: Any) -> Iterator:
    """Yield up to ``scan_limit`` dataset records, warning if more matched."""
    seen = 0
    offset = 0
    while seen < scan_limit:
        page = client.datasets.list(
            offset=offset, limit=min(100, scan_limit - seen), **filters
        )
        for dataset in page.results:
            yield dataset
            seen += 1
        offset += len(page.results)
        if not page.results:
            return
        if seen >= scan_limit and page.total > scan_limit:
            print(
                f"warning: scanned {scan_limit} of {page.total} matching datasets; "
                f"raise --scan-limit or narrow with dataset filters to cover the rest.",
                file=sys.stderr,
            )
            return


def _asset_matches(
    asset: Any, description: str | None, file_format: str | None, asset_type: str | None
) -> bool:
    if description is not None:
        text = asset.description or ""
        if description.lower() not in text.lower():
            return False
    if file_format is not None:
        text = asset.file_format or ""
        if file_format.lower() not in text.lower():
            return False
    if (
        asset_type is not None
        and getattr(asset.asset_type, "value", None) != asset_type
    ):
        return False
    return True


def _asset_row(dataset: Any, asset: Any) -> dict:
    return {
        "dataset_id": dataset.id,
        "canonical_id": dataset.canonical_id,
        "version": dataset.version,
        "asset_id": asset.id,
        "asset_type": getattr(asset.asset_type, "value", asset.asset_type),
        "file_format": asset.file_format,
        "storage_platform": getattr(
            asset.storage_platform, "value", asset.storage_platform
        ),
        "location_uri": asset.location_uri,
        "description": asset.description,
    }


def _truncate(value: Any, width: int) -> str:
    text = "" if value is None else str(value).strip()
    return text if len(text) <= width else text[: width - 1] + "…"


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("(no matching assets)")
        return
    columns = [
        ("canonical_id", "DATASET", 28),
        ("version", "VER", 7),
        ("file_format", "FORMAT", 10),
        ("storage_platform", "PLATFORM", 10),
        ("description", "DESCRIPTION", 50),
    ]
    headers = [header for _, header, _ in columns]
    cells = [
        [_truncate(row.get(key), width) for key, _, width in columns] for row in rows
    ]
    widths = [len(h) for h in headers]
    for line in cells:
        widths = [max(w, len(c)) for w, c in zip(widths, line)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for line in cells:
        print(fmt.format(*line))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="filter_assets",
        description="Filter a catalog's data assets by description / format / type.",
    )
    parser.add_argument(
        "--description", help="case-insensitive substring to match in asset description"
    )
    parser.add_argument(
        "--file-format", help="case-insensitive substring to match in asset file_format"
    )
    parser.add_argument("--asset-type", choices=[m.value for m in AssetType])
    parser.add_argument("--project")
    parser.add_argument("--modality")
    parser.add_argument("--canonical-id")
    parser.add_argument("--access-scope")
    parser.add_argument(
        "--all-versions",
        action="store_true",
        help="include non-latest dataset versions (default: latest only)",
    )
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=1000,
        help="max datasets to fetch and scan (default: 1000)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="max matching assets to return (default: 100)",
    )
    parser.add_argument("-o", "--output", choices=["table", "json"], default=None)
    args = parser.parse_args(argv)

    if not any([args.description, args.file_format, args.asset_type]):
        _usage_error(
            "give at least one asset filter: --description, --file-format or --asset-type."
        )
    if args.output is None:
        args.output = "table" if sys.stdout.isatty() else "json"

    filters: dict[str, Any] = {"is_latest": None if args.all_versions else True}
    if args.project:
        filters["project"] = args.project
    if args.canonical_id:
        filters["canonical_id"] = args.canonical_id
    if args.access_scope:
        filters["access_scope"] = args.access_scope
    modality = _modality(args.modality)
    if modality is not None:
        filters["modality"] = modality

    rows: list[dict] = []
    try:
        with _client() as client:
            for dataset in _iter_datasets(client, args.scan_limit, **filters):
                for asset in dataset.locations:
                    if _asset_matches(
                        asset, args.description, args.file_format, args.asset_type
                    ):
                        rows.append(_asset_row(dataset, asset))
                        if len(rows) >= args.limit:
                            break
                if len(rows) >= args.limit:
                    print(
                        f"note: stopped at --limit {args.limit} matching assets; "
                        "raise --limit for more.",
                        file=sys.stderr,
                    )
                    break
    except CatalogError as exc:
        print(f"error: request failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

    if args.output == "json":
        print(json.dumps({"count": len(rows), "assets": rows}, indent=2, default=str))
    else:
        _print_table(rows)


if __name__ == "__main__":
    main()
