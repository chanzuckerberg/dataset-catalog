#!/usr/bin/env python3
"""Validate a draft catalog record (JSON) before registration.

    validate_record.py PATH|-  [--model dataset|asset|collection|lineage]

Checks asset locations against the shared-storage rule, and for dataset records
runs `catalog validate` (the installed client's pydantic validation) and merges
its findings. Without the `catalog` CLI, or for other models, only the
shared-storage rule is checked, and the `valid` line says so. Misspelt keys are
not caught: the client's models ignore or keep unknown keys.

Output matches `catalog validate`: `valid`, or one `<dotted.path>: <message>`
line per problem. Exit 0 = valid, 1 = invalid, 2 = unreadable input.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
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


def cli_errors(text: str) -> list[str] | None:
    """Run `catalog validate -` when available; None when it can't (absent or too old)."""
    cli = shutil.which("catalog")
    if not cli:
        return None
    try:
        result = subprocess.run(
            [cli, "validate", "-"],
            input=text,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode not in (0, 1):
        return None
    return [
        line
        for line in result.stdout.splitlines()
        if line.strip() and line.strip() != "valid"
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a draft catalog record.")
    parser.add_argument("path", help="JSON record file, or - for stdin")
    parser.add_argument(
        "--model",
        default="dataset",
        choices=["dataset", "asset", "collection", "lineage"],
    )
    parser.add_argument(
        "--no-cli",
        action="store_true",
        help="skip `catalog validate` even if installed",
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
    schema_errors = None
    if args.model == "dataset" and not args.no_cli:
        schema_errors = cli_errors(text)
    errors = list(dict.fromkeys(errors + (schema_errors or [])))
    if errors:
        print("\n".join(errors))
        return 1
    if schema_errors is None:
        if args.model != "dataset":
            reason = f"{args.model} records have no CLI check"
        elif args.no_cli:
            reason = "--no-cli was passed"
        else:
            reason = "the `catalog` CLI is not installed or too old"
        print(
            f"valid (shared-storage rule only: {reason}; read field shapes from the "
            "installed client's model_json_schema(), registration-script skill)"
        )
        return 0
    print("valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
