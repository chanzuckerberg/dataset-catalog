#!/usr/bin/env python3
"""Map source dataset metadata to the latest catalog schema (v1.4.0) and register it.

This is the TEMPLATE the model-and-register-dataset skill produces. To use it
for a real dataset:

  1. Replace ``load_source()`` with your real loader (a CSV row, a LIMS export,
     a JSON blob — whatever the user has). ``SOURCE`` below is a stand-in.
  2. Adjust ``build_request()`` so every source field lands in the right schema
     slot. That function IS the field mapping — each line maps one piece of the
     user's data onto a v1.4.0 builder call. See
     docs/dataset-model/dataset-schema.md for the authoritative field reference.
  3. Validate the mapping offline (no token, no network):
        uv run python .claude/skills/model-and-register-dataset/register_dataset.py --dry-run
  4. Register against the real catalog:
        export CATALOG_API_URL=https://your-catalog.example.com
        export CATALOG_API_TOKEN=...      # issue at <catalog>/docs -> /token/issue
        uv run python .claude/skills/model-and-register-dataset/register_dataset.py --submit

``--dry-run`` validates the model with the same Pydantic rules the API enforces
and then exercises the full register() flow against an in-process fake catalog,
so a green dry-run means the mapping is wire-valid and the submit path works.
"""

from __future__ import annotations

import json
import os
import sys

import httpx

from catalog_client import (
    AssetType,
    BiologicalAnnotation,
    CatalogClient,
    ChannelMetadata,
    DatasetModality,
    DatasetType,
    OntologyEntry,
    StoragePlatform,
    TissueEntry,
)
from catalog_client.client.collections_ import CollectionClient
from catalog_client.client.datasets import DatasetClient
from catalog_client.client.lineages import LineageClient

# ===========================================================================
# 1. SOURCE — the data the user already has (REPLACE with your real loader).
#    Keys here are arbitrary; they are whatever the user's system calls things.
# ===========================================================================
SOURCE = {
    "dataset_id": "evican-brightfield-batch-01",
    "title": "EVICAN brightfield batch 01",
    "release": "1.0.0",
    "program": "cell-imaging-atlas",
    "kind": "raw",  # -> DatasetType
    "modality": "imaging",  # -> DatasetModality
    "summary": "Brightfield microscopy cell-segmentation training set.",
    # storage
    "uri": "s3://czi-imaging/evican/batch-01/",
    "is_folder": True,
    "bytes": 1_073_741_824,
    "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "format": "tiff",
    # governance
    "license": "CC-BY-4.0",
    "visibility": "public",
    "owner_email": "imaging-team@example.org",
    "has_phi": False,
    # experiment
    "sub_modality": "brightfield",
    "assay": {"label": "brightfield microscopy", "id": "EFO:0010415"},
    # sample
    "species": {"label": "Homo sapiens", "id": "NCBITaxon:9606"},
    "tissue": {"label": "epithelium", "id": "UBERON:0000483", "type": "cell line"},
    # data summary
    "cell_count": 48211,
    "channels": [
        {"name": "brightfield", "type": "labelfree"},
        {"name": "DAPI", "type": "fluorescence", "target": "nucleus", "marker": "DAPI"},
    ],
    # quality
    "qc_passed": ["schema_valid", "checksum_match"],
}


def load_source() -> dict:
    """Return the user's raw metadata. REPLACE this body with a real loader."""
    return SOURCE


# Map storage URI scheme -> StoragePlatform. Extend for your storage backends.
def _storage_platform(uri: str) -> StoragePlatform:
    if uri.startswith("s3://"):
        return StoragePlatform.s3
    return StoragePlatform.other


# ===========================================================================
# 2. build_request — THE MAPPING. Each line places a SOURCE field into the
#    v1.4.0 schema via a builder call. Edit to fit the user's fields.
# ===========================================================================
def build_request(client: CatalogClient, src: dict):
    builder = (
        client.new_registration(
            canonical_id=src["dataset_id"],  # -> canonical_id (signature)
            name=src["title"],  # -> name
            version=src["release"],  # -> version (signature)
            project=src["program"],  # -> project (signature)
            modality=DatasetModality(src["modality"]),  # -> modality
        )
        .described(src["summary"])  # -> description
        .of_type(DatasetType(src["kind"]))  # -> dataset_type (raw|processed)
        # locations[] (>=1 required) -------------------------------------
        .with_location(
            src["uri"],  # -> location_uri (signature)
            asset_type=AssetType.folder if src["is_folder"] else AssetType.file,
            storage_platform=_storage_platform(src["uri"]),
            size_bytes=src.get("bytes"),  # -> size_bytes (signature)
            checksum=src.get("sha256"),  # -> checksum (signature)
            checksum_alg="sha256" if src.get("sha256") else None,
            file_format=src.get("format"),
        )
        # governance (required block) ------------------------------------
        .with_governance(
            license=src.get("license"),
            access_scope=src.get("visibility"),  # "public" | "internal"
            data_owner=src.get("owner_email"),
            is_phi=src.get("has_phi", False),
        )
        # metadata.experiment --------------------------------------------
        .with_experiment(
            sub_modality=src.get("sub_modality"),
            assay=[
                OntologyEntry(
                    label=src["assay"]["label"], ontology_id=src["assay"]["id"]
                )
            ],
        )
        # metadata.sample ------------------------------------------------
        .with_sample(
            organism=[
                OntologyEntry(
                    label=src["species"]["label"], ontology_id=src["species"]["id"]
                )
            ],
            tissue=[
                TissueEntry(
                    label=src["tissue"]["label"],
                    ontology_id=src["tissue"]["id"],
                    type=src["tissue"].get("type"),
                )
            ],
        )
        # metadata.data_summary (channels mapped from a list) ------------
        .with_data_summary(
            cell_count=src.get("cell_count"),
            channels=[_map_channel(ch) for ch in src.get("channels", [])],
        )
        # data_quality (checks_* accept any shape: list / count / dict) --
        .with_data_quality(checks_passed=src.get("qc_passed"), checks_failed=[])
    )
    return builder


def _map_channel(ch: dict) -> ChannelMetadata:
    """Map one source channel dict -> ChannelMetadata (+ BiologicalAnnotation)."""
    annotation = None
    if ch.get("target") or ch.get("marker"):
        annotation = BiologicalAnnotation(
            biological_target=ch.get("target"),
            marker=ch.get("marker"),
        )
    return ChannelMetadata(
        name=ch.get("name"),
        channel_type=ch.get("type"),
        biological_annotation=annotation,
    )


# ===========================================================================
# Offline validation harness: an in-process fake catalog for --dry-run.
# ===========================================================================
_NEW_ID = "00000000-0000-4000-8000-000000000000"


def _fake_catalog(request: httpx.Request) -> httpx.Response:
    path, method = request.url.path, request.method
    if method == "GET" and path == "/api/datasets/":
        return httpx.Response(
            200, json={"total": 0, "limit": 10, "offset": 0, "results": []}
        )
    if method == "POST" and path == "/api/datasets/":
        body = json.loads(request.content)
        server = {
            "tombstoned": False,
            "created_at": "2026-06-16T00:00:00Z",
            "last_modified_at": "2026-06-16T00:00:00Z",
        }
        locations = [
            {**loc, "id": f"asset-{i}", "dataset_id": _NEW_ID, **server}
            for i, loc in enumerate(body.get("locations", []))
        ]
        return httpx.Response(
            201,
            json={
                **body,
                "id": _NEW_ID,
                "created_by": "tok",
                "modified_by": None,
                "record_version": 1,
                "locations": locations,
                **server,
            },
        )
    return httpx.Response(500, json={"detail": f"unrouted {method} {path}"})


def _mock_client() -> CatalogClient:
    client = CatalogClient(base_url="http://mock.local", api_token="tok")
    http = httpx.Client(
        base_url="http://mock.local/api/",
        headers={"X-catalog-api-token": "tok"},
        transport=httpx.MockTransport(_fake_catalog),
    )
    client._http = http
    client.datasets = DatasetClient(http)
    client.lineages = LineageClient(http)
    client.collections = CollectionClient(http)
    return client


def dry_run() -> int:
    src = load_source()
    client = _mock_client()
    builder = build_request(client, src)

    # Offline validation: same Pydantic rules the real API enforces.
    payload = (
        builder.build().to_dataset_request().model_dump(mode="json", exclude_none=True)
    )
    assert payload["record_schema_version"] == "v1.4.0", payload.get(
        "record_schema_version"
    )
    print(
        f"[mapping valid] schema={payload['record_schema_version']}  "
        f"canonical_id={payload['canonical_id']}  "
        f"locations={len(payload['locations'])}  "
        f"channels={len(payload['metadata']['data_summary']['channels'])}"
    )
    print(json.dumps(payload, indent=2))

    # Prove the full submit path against the fake catalog.
    dataset_id = builder.submit()
    print(
        f"\n[dry-run submit OK] would register -> dataset_id placeholder {dataset_id}"
    )
    client.close()
    return 0


def submit_real() -> int:
    base_url = os.environ.get("CATALOG_API_URL")
    token = os.environ.get("CATALOG_API_TOKEN")
    if not base_url or not token:
        print(
            "ERROR: set CATALOG_API_URL and CATALOG_API_TOKEN to submit.",
            file=sys.stderr,
        )
        return 2
    src = load_source()
    with CatalogClient(base_url=base_url, api_token=token) as client:
        dataset_id = build_request(client, src).submit()
    print(f"registered -> dataset_id={dataset_id}")
    return 0


def main(argv: list[str]) -> int:
    if "--submit" in argv:
        return submit_real()
    # default: dry-run (safe; no token/network)
    return dry_run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
