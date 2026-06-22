#!/usr/bin/env python3
"""Map source dataset metadata to the latest catalog schema (v1.4.0) and register it.

This is the TEMPLATE the catalog-register skill produces, and the
HARNESS you run while building a mapping. To use it for a real dataset:

  1. Replace ``load_source()`` with your real loader (a CSV row, a LIMS export,
     a JSON blob — whatever the user has). ``SOURCE`` below is a stand-in.
  2. Adjust ``build_request()`` so every source field lands in the right schema
     slot. That function IS the field mapping — each line maps one piece of the
     user's data onto a v1.4.0 builder call.

Commands (run while iterating on the mapping):

  # print the LIVE schema field tree (authoritative, never stale):
  uv run python .../register_dataset.py --fields

  # validate the mapping + see which source fields you dropped (no token/network):
  uv run python .../register_dataset.py --dry-run

  # register against the real catalog:
  export CATALOG_API_URL=https://your-catalog.example.com
  export CATALOG_API_TOKEN=...        # issue at <catalog>/docs -> /token/issue
  uv run python .../register_dataset.py --submit

``--dry-run`` validates with the same Pydantic rules the API enforces, prints
the payload, exercises the full register() flow against an in-process fake
catalog, and reports mapping COVERAGE (which source fields were used, dropped,
or silently left behind).
"""

from __future__ import annotations

import json
import os
import sys
import typing

import httpx
from pydantic import BaseModel

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
from catalog_client.models.dataset import DatasetRequest

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
    # source-specific attribute with no exact schema slot -> rides along as an extra
    "imaging_protocol_id": "PROTO-2025-118",
    # quality
    "qc_passed": ["schema_valid", "checksum_match"],
    # operational fields we deliberately do NOT carry into the catalog
    "internal_row_id": 90432,
}


def load_source() -> dict:
    """Return the user's raw metadata. REPLACE this body with a real loader."""
    return SOURCE


class Source:
    """Dict wrapper that records which keys the mapping reads.

    Lets ``--dry-run`` report mapping coverage: any source field you never read
    and never explicitly ``drop()`` is flagged as silently lost — the most
    common mapping bug. Read with ``src["x"]`` / ``src.get("x")``; mark fields
    you intentionally omit with ``src.drop("x", "y")``.
    """

    def __init__(self, data: dict) -> None:
        self._data = dict(data)
        self._used: set[str] = set()
        self._dropped: set[str] = set()

    def __getitem__(self, key: str):
        self._used.add(key)
        return self._data[key]

    def get(self, key: str, default=None):
        self._used.add(key)
        return self._data.get(key, default)

    def drop(self, *keys: str) -> None:
        """Acknowledge source fields that are intentionally not mapped."""
        self._dropped.update(keys)

    def unmapped(self) -> list[str]:
        return sorted(set(self._data) - self._used - self._dropped)

    def stats(self) -> tuple[int, int, int]:
        total = len(self._data)
        return len(self._used & self._data.keys()), len(self._dropped), total


# Map storage URI scheme -> StoragePlatform. Extend for your storage backends.
# WARNING: schemes are ambiguous. A "/hpc/..." path is not always sf_hpc (also
# chi_hpc / ny_hpc), and an http(s):// URI is not always `external` (internal
# platforms can sit behind a URL). Confirm the platform with the user when the
# path alone doesn't make it obvious. Members: s3, sf_hpc, chi_hpc, ny_hpc,
# reef, kelp, external, other.
def _storage_platform(uri: str) -> StoragePlatform:
    if uri.startswith("s3://"):
        return StoragePlatform.s3
    if uri.startswith(("http://", "https://")):
        return StoragePlatform.external
    return StoragePlatform.other


def _ontology(entry: dict, *, id_key: str = "id") -> OntologyEntry:
    """Normalize a source ontology dict to OntologyEntry.

    Source systems name the id field differently (`id`, `ontology_term_id`,
    `term_id`); the catalog field is always `ontology_id`.
    """
    return OntologyEntry(label=entry.get("label"), ontology_id=entry.get(id_key))


# ===========================================================================
# 2. build_request — THE MAPPING. Each line places a SOURCE field into the
#    v1.4.0 schema via a builder call. Edit to fit the user's fields.
# ===========================================================================
def build_request(client: CatalogClient, src: Source):
    builder = (
        client.new_registration(
            canonical_id=src["dataset_id"],  # -> canonical_id (signature)
            name=src["title"],  # -> name
            version=src.get("release") or "1.0.0",  # never null; default "1.0.0"
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
            access_scope="internal",  # always "internal" — never map from source
            data_owner=src.get("owner_email"),
            # Never assume PII/PHI status. Leave None (unknown) when the source
            # is silent — do NOT default to False. Confirm both with the user.
            is_pii=src.get("has_pii"),
            is_phi=src.get("has_phi"),
        )
        # metadata.experiment --------------------------------------------
        .with_experiment(
            sub_modality=src.get("sub_modality"),
            assay=[_ontology(src["assay"])],
        )
        # metadata.sample ------------------------------------------------
        .with_sample(
            organism=[_ontology(src["species"])],
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
        # EXTRAS: source fields that don't fall into sample / experiment /
        # data_summary. Every metadata block has extra="allow", so unknown keys
        # are preserved rather than dropped. Group all such dataset-level extras
        # under the single `additional_metadata` key in the metadata block.
        .with_custom_metadata(
            additional_metadata={"imaging_protocol_id": src.get("imaging_protocol_id")}
        )
        # data_quality (checks_* accept any shape: list / count / dict) --
        .with_data_quality(checks_passed=src.get("qc_passed"), checks_failed=[])
    )

    # Fields intentionally NOT carried into the catalog (operational only).
    src.drop("internal_row_id")
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
# Live schema introspection (--fields). Reads the actual pydantic models, so
# it never goes stale the way a hand-written doc can.
# ===========================================================================
def _type_name(annotation) -> str:
    if isinstance(annotation, type):  # plain class or enum -> just its name
        return annotation.__name__
    return (
        str(annotation)
        .replace("catalog_client.models.", "")
        .replace("typing.", "")
        .replace("NoneType", "None")
    )


def _nested_models(annotation) -> list[type[BaseModel]]:
    out: list[type[BaseModel]] = []
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        out.append(annotation)
    for arg in typing.get_args(annotation):
        out.extend(_nested_models(arg))
    return out


def print_schema_fields(
    model: type[BaseModel] = DatasetRequest,
    indent: int = 0,
    seen: set[type] | None = None,
) -> None:
    seen = seen if seen is not None else set()
    if indent == 0:
        allows = model.model_config.get("extra") == "allow"
        print(f"{model.__name__}{'  [extra=allow]' if allows else ''}")
    for name, field in model.model_fields.items():
        req = "*" if field.is_required() else " "
        print(f"{'  ' * (indent + 1)}{req} {name}: {_type_name(field.annotation)}")
        for nested in _nested_models(field.annotation):
            if nested not in seen:
                seen.add(nested)
                allows = nested.model_config.get("extra") == "allow"
                tag = "  [extra=allow]" if allows else ""
                print(f"{'  ' * (indent + 2)}> {nested.__name__}{tag}")
                print_schema_fields(nested, indent + 2, seen)


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


def _coverage(src: Source, payload: dict) -> None:
    used, dropped, total = src.stats()
    print(f"\n[coverage] {used} mapped + {dropped} dropped of {total} source fields")
    unmapped = src.unmapped()
    if unmapped:
        print(f"  ⚠ SILENTLY LOST (read nowhere, not dropped): {', '.join(unmapped)}")
        print("    -> map them, or src.drop(...) to acknowledge they're omitted")
    else:
        print("  ✓ every source field is mapped or explicitly dropped")
    blocks = [
        b
        for b in ("experiment", "sample", "data_summary")
        if payload.get("metadata", {}).get(b)
    ]
    print(f"  metadata blocks populated: {', '.join(blocks) or 'none'}")


def dry_run() -> int:
    src = Source(load_source())
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
        f"locations={len(payload['locations'])}"
    )
    print(json.dumps(payload, indent=2))

    # Prove the full submit path against the fake catalog.
    dataset_id = builder.submit()
    print(
        f"\n[dry-run submit OK] would register -> dataset_id placeholder {dataset_id}"
    )
    _coverage(src, payload)
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
    src = Source(load_source())
    with CatalogClient(base_url=base_url, api_token=token) as client:
        dataset_id = build_request(client, src).submit()
    print(f"registered -> dataset_id={dataset_id}")
    return 0


def main(argv: list[str]) -> int:
    if "--fields" in argv:
        print_schema_fields()
        return 0
    if "--submit" in argv:
        return submit_real()
    # default: dry-run (safe; no token/network)
    return dry_run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
