"""Shared record fixtures for the dataframe tests."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from catalog_client.client.catalog import CatalogClient
from catalog_client.models.dataset import DatasetResponse

BASE = "http://test.local"
API = "http://test.local/api/"
TOKEN = "tok"

DATASET: dict[str, Any] = {
    "id": "uuid-1",
    "tombstoned": False,
    "created_at": "2024-01-01T00:00:00Z",
    "last_modified_at": "2024-01-02T00:00:00Z",
    "canonical_id": "ds-001",
    "version": "1.0.0",
    "project": "atlas",
    "name": "Test dataset",
    "modality": "imaging",
    "dataset_type": "raw",
    "is_latest": True,
    "record_version": 1,
    "description": None,
    "doi": None,
    "cross_db_references": None,
    "record_schema_version": None,
    "metadata_schema": None,
    "data_quality": None,
    "governance": {"license": "MIT", "access_scope": "public"},
    "metadata": {
        "sample": {
            "organism": [
                {"label": "Homo sapiens", "ontology_id": "NCBITaxon:9606"},
                {"label": "Mus musculus", "ontology_id": "NCBITaxon:10090"},
            ],
            "tissue": [{"label": "liver", "ontology_id": "UBERON:0002107"}],
            "disease": [{"label": "carcinoma", "ontology_id": "MONDO:0004993"}],
        },
        "experiment": {"sub_modality": "confocal"},
        "data_summary": {
            "dimension": [512, 512, 40],
            "channels": [
                {"name": "c1", "biological_annotation": {"marker": "DAPI"}},
                {"name": "c2", "biological_annotation": {"marker": "GFP"}},
            ],
        },
    },
    "locations": [
        {
            "id": "asset-1",
            "dataset_id": "uuid-1",
            "tombstoned": False,
            "created_at": "2024-01-01T00:00:00Z",
            "last_modified_at": "2024-01-01T00:00:00Z",
            "location_uri": "s3://bucket/a.zarr",
            "asset_type": "folder",
            "size_bytes": 100,
        },
        {
            "id": "asset-2",
            "dataset_id": "uuid-1",
            "tombstoned": False,
            "created_at": "2024-01-01T00:00:00Z",
            "last_modified_at": "2024-01-01T00:00:00Z",
            "location_uri": "s3://bucket/b.zarr",
            "asset_type": "file",
            "size_bytes": 250,
        },
    ],
}


def dataset_dict(**overrides: Any) -> dict[str, Any]:
    """A dataset payload with top-level fields overridden."""
    payload = copy.deepcopy(DATASET)
    payload.update(overrides)
    return payload


def dataset_model(**overrides: Any) -> DatasetResponse:
    """The same payload, parsed into a model."""
    return DatasetResponse.model_validate(dataset_dict(**overrides))


def list_page(results: list[dict[str, Any]], next_cursor: str | None = None) -> dict:
    return {
        "total": None,
        "limit": 100,
        "offset": None,
        "results": results,
        "next_cursor": next_cursor,
    }


def search_page(results: list[dict[str, Any]], next_cursor: str | None = None) -> dict:
    return {
        "total": len(results),
        "limit": 100,
        "results": results,
        "next_cursor": next_cursor,
        "facets": None,
    }


@pytest.fixture
def client() -> CatalogClient:
    return CatalogClient(base_url=BASE, api_token=TOKEN)
