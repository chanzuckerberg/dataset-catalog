#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "catalog-client>=1.3.0,<2",
# ]
# ///
"""Register datasets with the Scientific Dataset Catalog.

Generated from the catalog plugin's registration template. Typical use:

    python register.py --dry-run               # staging: validate + plan, no writes
    python register.py                         # staging: register
    python register.py --env prod --dry-run    # production: validate + plan
    python register.py --env prod              # production: register

Data-specific values live in mapping.json (--config). Credentials are read
from the environment by name: CATALOG_STAGING_API_TOKEN / CATALOG_PROD_API_TOKEN,
or CATALOG_API_TOKEN when CATALOG_API_URL names the same environment.

Exit codes: 0 = every record succeeded; 1 = at least one record failed;
2 = configuration, credential, or client/API compatibility error.
"""

# === TEMPLATE-OWNED: do not edit (checked by PostToolUse hook) ===
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import logging
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from catalog_client import (
    CatalogClient,
    CompatibilityError,
    RetryPolicy,
    check_compatibility,
    run_batch,
)
from catalog_client.models.asset import DataAssetRequest
from catalog_client.registration import (
    LineageSpec,
    RegistrationBuilder,
    RegistrationRequest,
)

ENVIRONMENTS = {
    "staging": "https://datacatalog.staging-sci-data.staging.czi.team",
    "prod": "https://datacatalog.prod-sci-data.prod.czi.team",
}
MAX_WORKERS = 16
EXIT_CONFIG = 2
DRY_RUN_MARKER = "catalog-dry-run: ok"

log = logging.getLogger("register")


@dataclass
class Source:
    """One dataset to register: a stable key plus whatever discover_records found."""

    key: str
    attrs: dict[str, Any] = field(default_factory=dict)


class ConfigError(Exception):
    pass


def resolve_token(env: str) -> tuple[str, str]:
    specific, generic = f"CATALOG_{env.upper()}_API_TOKEN", "CATALOG_API_TOKEN"
    if os.environ.get(specific):
        return specific, os.environ[specific]
    # The generic variable is trusted only when it is paired with this environment's URL.
    if (
        os.environ.get(generic)
        and (os.environ.get("CATALOG_API_URL") or "").rstrip("/") == ENVIRONMENTS[env]
    ):
        return generic, os.environ[generic]
    raise ConfigError(
        f"no token for {env}: set {specific} (or {generic} with CATALOG_API_URL={ENVIRONMENTS[env]})"
    )


def load_config(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc.strerror or exc}") from exc
    except ValueError as exc:
        raise ConfigError(f"config {path} is not valid JSON: {exc}") from exc


def build_request(src: Source, config: dict) -> RegistrationRequest:
    request = build_dataset(src, config).build()
    request.locations.extend(build_assets(src, config))
    request.lineage.extend(lineage_parents(src, config))
    return request


def _payload_path(directory: Path, key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", key).strip("_") or "record"
    return directory / f"{safe}-{hashlib.sha256(key.encode()).hexdigest()[:8]}.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register datasets with the Scientific Dataset Catalog."
    )
    parser.add_argument("--env", choices=sorted(ENVIRONMENTS), default="staging")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate and plan only; never writes"
    )
    parser.add_argument(
        "--config", type=Path, default=Path(__file__).with_name("mapping.json")
    )
    parser.add_argument(
        "--limit", type=int, help="process at most N records (for a first trial run)"
    )
    parser.add_argument(
        "--workers", type=int, default=4, help=f"concurrent records, 1-{MAX_WORKERS}"
    )
    parser.add_argument(
        "--payload-dir",
        type=Path,
        default=Path("catalog-dry-run"),
        help="where --dry-run writes each payload",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= MAX_WORKERS:
        parser.error(f"--workers must be between 1 and {MAX_WORKERS}")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be >= 1")
    return args


def make_handler(client: CatalogClient, config: dict, args: argparse.Namespace):
    def handle(src: Source) -> None:
        request = build_request(src, config)
        # Local pydantic validation: a bad record fails here, before any API call.
        payload = request.to_dataset_request()
        collections = collections_for(src, config)
        if args.dry_run:
            plan = client.plan(request, update_if_exists=True, error_on_duplicate=False)
            for collection_id in collections:
                client.collections.get(collection_id)
            args.payload_dir.mkdir(parents=True, exist_ok=True)
            _payload_path(args.payload_dir, src.key).write_text(
                json.dumps(payload.model_dump(mode="json", exclude_none=True), indent=2)
                + "\n"
            )
            log.info(
                "%s: would %s (dataset %s; %d collection(s))",
                src.key,
                plan.action,
                plan.dataset_id or "(new dataset)",
                len(collections),
            )
            for edge in plan.lineage_to_create:
                # On a create the destination id does not exist yet and comes back empty.
                log.info(
                    "%s: would link %s %s -> %s",
                    src.key,
                    edge.lineage_type.value,
                    edge.source_dataset_id,
                    edge.destination_dataset_id or "(new dataset)",
                )
            return
        dataset_id = client.register(
            request, update_if_exists=True, error_on_duplicate=False
        )
        for collection_id in collections:
            client.collections.add_dataset(collection_id, dataset_id)
        log.info("%s: registered %s", src.key, dataset_id)

    return handle


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s"
    )
    try:
        config = load_config(args.config)
        token_var, token = resolve_token(args.env)
    except ConfigError as exc:
        log.error("%s", exc)
        return EXIT_CONFIG
    log.info(
        "env=%s url=%s token=%s dry_run=%s",
        args.env,
        ENVIRONMENTS[args.env],
        token_var,
        args.dry_run,
    )
    retry = RetryPolicy(max_attempts=5, base_delay=0.5, max_delay=30.0, jitter=True)
    with CatalogClient(
        base_url=ENVIRONMENTS[args.env], api_token=token, retry=retry
    ) as client:
        try:
            check_compatibility(client)
        except CompatibilityError as exc:
            log.error("client/API mismatch: %s", exc)
            return EXIT_CONFIG
        records: Iterator[Source] = discover_records(config)
        if args.limit:
            records = itertools.islice(records, args.limit)
        report = run_batch(
            records,
            make_handler(client, config, args),
            key=lambda src: src.key,
            max_workers=args.workers,
            logger=log,
        )
    print(report.summary("planned" if args.dry_run else "registered"))
    if args.dry_run and report.exit_code == 0:
        # Read by the plugin's PreToolUse guard: a production run needs a passing dry run of these exact files.
        script, mapping = Path(__file__).resolve(), args.config.resolve()
        print(
            f"{DRY_RUN_MARKER} env={args.env} script={script} script_sha256={_sha256(script)} "
            f"config={mapping} config_sha256={_sha256(mapping)}"
        )
    return report.exit_code


# === AGENT-EDITABLE ===
# Only the functions below and mapping.json change per dataset. Read every
# data-specific value (paths, patterns, governance) from `config`.
from catalog_client import (  # noqa: E402
    AssetType,
    DatasetModality,
    DatasetRef,
    DatasetType,
    LineageType,
    OntologyEntry,
)
from catalog_client.models.asset import StoragePlatform  # noqa: E402
from catalog_client.utils.checksum import Algorithm, compute_checksum  # noqa: E402


def discover_records(config: dict) -> Iterator[Source]:
    """Yield one Source per dataset. Stream: never collect every record first."""
    data = config["data"]
    for entry in Path(data["root"]).glob(data["dataset_glob"]):
        if entry.is_dir():
            yield Source(key=entry.name, attrs={"path": entry})


def build_dataset(src: Source, config: dict) -> RegistrationBuilder:
    dataset = config["dataset"]
    builder = (
        RegistrationBuilder(
            canonical_id=f"{dataset['canonical_id_prefix']}/{src.key}",
            name=f"{dataset['name_prefix']} {src.key}",
            version=dataset.get("version") or "1.0.0",
            project=dataset["project"],
            modality=DatasetModality(dataset["modality"]),
        )
        .of_type(DatasetType(dataset["dataset_type"]))
        .with_governance(**config["governance"])
        .with_sample(
            organism=[OntologyEntry(**entry) for entry in dataset.get("organism", [])]
        )
    )
    if dataset.get("description"):
        builder.described(dataset["description"])
    return builder


def build_assets(src: Source, config: dict) -> list[DataAssetRequest]:
    """One folder asset per dataset; the checksum streams, files are never read whole."""
    path: Path = src.attrs["path"]
    assets = config["assets"]
    result = compute_checksum(
        str(path), algorithm=Algorithm(assets["checksum_algorithm"])
    )
    file_count = sum(len(files) for _, _, files in os.walk(path))
    return [
        DataAssetRequest(
            location_uri=os.path.abspath(path),
            asset_type=AssetType.folder,
            storage_platform=StoragePlatform(assets["storage_platform"]),
            file_format=assets.get("file_format"),
            size_bytes=result.total_size,
            checksum=result.content_digest,
            checksum_alg=result.algorithm.value,
            file_count=file_count,
        )
    ]


def lineage_parents(src: Source, config: dict) -> list[LineageSpec]:
    """Parents must already be registered; the client resolves each DatasetRef to its id."""
    return [
        LineageSpec(
            lineage_type=LineageType(parent["lineage_type"]),
            source_ref=DatasetRef(
                parent["canonical_id"], parent["version"], parent["project"]
            ),
        )
        for parent in config.get("lineage_parents", [])
    ]


def collections_for(src: Source, config: dict) -> list[str]:
    """Collection ids (must already exist) each registered dataset is added to."""
    return list(config.get("collections", []))


# === END AGENT-EDITABLE ===
if __name__ == "__main__":
    sys.exit(main())
