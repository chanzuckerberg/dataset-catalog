#!/usr/bin/env python3
"""Validate a draft catalog record (JSON) before registration.

    validate_record.py PATH|-  [--model dataset|asset|collection|lineage]

Checks asset locations against the shared-storage rule only. Field types,
required fields and allowed values are checked by the registration script's
`--dry-run`, which validates with the installed client before any API call.

Output: `valid (shared-storage rule only ...)`, or one `<dotted.path>: <message>`
line per problem. Exit 0 = valid, 1 = invalid, 2 = unreadable input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Keep in sync with the registration template (tests/test_shared_rules.py checks both).
CLUSTER_PLATFORMS = frozenset({"sf_hpc", "chi_hpc", "ny_hpc", "reef", "kelp", "atoll"})
PERSONAL_PATH_PREFIXES = (
    "/home/",
    "/Users/",
    "/tmp/",
    "/var/tmp/",
    "/private/",
    "/var/folders/",
    "/Volumes/",
)


def location_problem(uri: str, platform: str) -> str | None:
    """Why an asset location may not be registered; None when it is shared organization storage."""
    if uri.lower().startswith("file:"):
        return "file:// URIs point at one machine's disk"
    if "://" in uri:
        return None
    if not uri.startswith("/"):
        return "relative and home-directory paths point at one machine's disk"
    if platform not in CLUSTER_PLATFORMS:
        return (
            f"a bare path is only registrable on shared cluster storage "
            f"({', '.join(sorted(CLUSTER_PLATFORMS))}), not storage_platform {platform!r}"
        )
    if uri.startswith(PERSONAL_PATH_PREFIXES):
        return "personal or machine-local directory"
    return None


def location_errors(record: object, model: str) -> list[str]:
    if not isinstance(record, dict):
        return []
    assets = record.get("locations") if model == "dataset" else [record]
    if model not in ("dataset", "asset") or not isinstance(assets, list):
        return []
    errors = []
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict) or not isinstance(
            asset.get("location_uri"), str
        ):
            continue
        problem = location_problem(
            asset["location_uri"], str(asset.get("storage_platform"))
        )
        if problem:
            prefix = f"locations.{index}." if model == "dataset" else ""
            errors.append(
                f"{prefix}location_uri: not registrable, {problem}; register only data on "
                "shared organization storage (catalog-guide skill)"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a draft catalog record.")
    parser.add_argument("path", help="JSON record file, or - for stdin")
    parser.add_argument(
        "--model",
        default="dataset",
        choices=["dataset", "asset", "collection", "lineage"],
    )
    args = parser.parse_args(argv)

    try:
        text = sys.stdin.read() if args.path == "-" else Path(args.path).read_text()
    except OSError as exc:
        print(f"error: {args.path}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    try:
        record = json.loads(text)
    except ValueError as exc:
        print(
            f"error: {args.path}: not valid JSON ({exc}); YAML records are not supported",
            file=sys.stderr,
        )
        return 2

    errors = location_errors(record, args.model)
    if errors:
        print("\n".join(errors))
        return 1
    print(
        "valid (shared-storage rule only; run the registration script with "
        "--dry-run to check fields against the installed client)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
