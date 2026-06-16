"""Tests for the client<->API gap fixes (fix/client-api-gaps)."""

import json
import re

import httpx
import pytest
from pytest_httpx import HTTPXMock

from catalog_client.client.catalog import AsyncCatalogClient, CatalogClient
from catalog_client.client.collections_ import AsyncCollectionClient, CollectionClient
from catalog_client.client.datasets import AsyncDatasetClient, DatasetClient
from catalog_client.exceptions import DuplicateDatasetError
from catalog_client.models.collection import CollectionChildType
from catalog_client.models.dataset import (
    AuditLogEventType,
    DatasetAuditLogResponse,
    DatasetModality,
    DatasetRequest,
    DatasetSearchResponse,
)
from catalog_client.models.lineage import LineageType
from catalog_client.models.pagination import PaginatedResponse

BASE = "http://test.local/api/"
TOKEN = "tok"

DATASET_RESPONSE = {
    "id": "uuid-1",
    "tombstoned": False,
    "created_at": "2024-01-01T00:00:00Z",
    "last_modified_at": "2024-01-01T00:00:00Z",
    "canonical_id": "ds-001",
    "version": "1.0.0",
    "project": "atlas",
    "locations": [],
    "name": "Test",
    "modality": "sequencing",
    "dataset_type": "raw",
    "governance": {},
    "data_quality": None,
    "metadata": {},
    "record_version": 1,
    "description": None,
    "doi": None,
    "cross_db_references": None,
    "is_latest": True,
    "record_schema_version": None,
    "metadata_schema": None,
}

COLLECTION_RESPONSE = {
    "id": "col-1",
    "tombstoned": False,
    "created_at": "2024-01-01T00:00:00Z",
    "last_modified_at": "2024-01-01T00:00:00Z",
    "canonical_id": "col-001",
    "version": "1.0.0",
    "name": "My Collection",
    "collection_owner": "team-x",
    "metadata": None,
    "description": None,
    "license": None,
    "doi": None,
    "collection_type": None,
}


def _datasets() -> DatasetClient:
    return DatasetClient(
        httpx.Client(base_url=BASE, headers={"X-catalog-api-token": TOKEN})
    )


def _async_datasets() -> AsyncDatasetClient:
    return AsyncDatasetClient(
        httpx.AsyncClient(base_url=BASE, headers={"X-catalog-api-token": TOKEN})
    )


def _collections() -> CollectionClient:
    return CollectionClient(httpx.Client(base_url=BASE))


def _async_collections() -> AsyncCollectionClient:
    return AsyncCollectionClient(httpx.AsyncClient(base_url=BASE))


# --- Bug 1a: remove_* return None on 204 ---


def test_remove_dataset_returns_none_on_204(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}collections/col-1/datasets/ds-1", method="DELETE", status_code=204
    )
    # Must not raise (previously crashed parsing the empty 204 body as JSON).
    _collections().remove_dataset("col-1", "ds-1")


def test_remove_collection_returns_none_on_204(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}collections/col-1/collections/col-2",
        method="DELETE",
        status_code=204,
    )
    _collections().remove_collection("col-1", "col-2")


async def test_async_remove_dataset_returns_none_on_204(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}collections/col-1/datasets/ds-1", method="DELETE", status_code=204
    )
    async with _async_collections() as client:
        await client.remove_dataset("col-1", "ds-1")


# --- Bug 1b: async _resolve must request limit <= 100 ---


async def test_async_resolve_uses_limit_within_max(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}datasets/\?.*"),
        json={"total": 1, "limit": 10, "offset": 0, "results": [DATASET_RESPONSE]},
    )
    httpx_mock.add_response(url=f"{BASE}datasets/uuid-1", json=DATASET_RESPONSE)
    from catalog_client.models.dataset import DatasetRef

    async with _async_datasets() as client:
        await client.get(DatasetRef("ds-001", "1.0.0", "atlas"))
    list_req = httpx_mock.get_requests()[0]
    assert int(list_req.url.params["limit"]) <= 100


# --- Gap 2: query params emitted only when set ---


def test_list_emits_access_scope_and_exclude_tombstoned(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}datasets/\?.*"),
        json={"total": 0, "limit": 100, "offset": 0, "results": []},
    )
    _datasets().list(access_scope="public", exclude_tombstoned=False)
    params = httpx_mock.get_request().url.params
    assert params["access_scope"] == "public"
    assert params["exclude_tombstoned"] == "false"


def test_get_emits_exclude_tombstoned_only_when_false(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}datasets/uuid-1.*"), json=DATASET_RESPONSE
    )
    _datasets().get("uuid-1", exclude_tombstoned=False)
    assert httpx_mock.get_request().url.params["exclude_tombstoned"] == "false"


def test_list_entries_emits_entry_type(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}collections/col-1/entries.*"),
        json={"total": 0, "limit": 100, "offset": 0, "results": []},
    )
    _collections().list_entries("col-1", entry_type=CollectionChildType.dataset)
    assert httpx_mock.get_request().url.params["entry_type"] == "dataset"


# --- Gap 3: new endpoints ---


def test_search_parses_response_with_facets(httpx_mock: HTTPXMock):
    body = {
        "total": 1,
        "limit": 10,
        "offset": 0,
        "results": [
            {
                "id": "uuid-1",
                "canonical_id": "ds-001",
                "version": "1.0.0",
                "name": "Test",
                "modality": "sequencing",
                "dataset_type": "raw",
                "project": "atlas",
                "is_latest": True,
                "access_scope": "public",
                "score": 1.5,
            }
        ],
        "facets": {"modality": [{"value": "sequencing", "count": 1}]},
    }
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}datasets/search/\?.*"), json=body
    )
    result = _datasets().search(
        q="test", facets=["modality"], modality=DatasetModality.sequencing
    )
    assert isinstance(result, DatasetSearchResponse)
    assert result.results[0].score == 1.5
    assert result.facets is not None
    assert result.facets["modality"][0].count == 1
    params = httpx_mock.get_request().url.params
    assert params["q"] == "test"
    assert params["facets"] == "modality"
    assert params["modality"] == "sequencing"


def test_history_parses_and_sends_skip(httpx_mock: HTTPXMock):
    body = {
        "total": 1,
        "limit": 10,
        "offset": 0,
        "results": [
            {
                "id": "audit-1",
                "dataset_id": "uuid-1",
                "event_type": "created",
                "actor": "tok-1",
                "timestamp": "2024-01-01T00:00:00Z",
                "db_created_at": "2024-01-01T00:00:00Z",
                "snapshot": {"name": "Test"},
            }
        ],
    }
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}datasets/uuid-1/history\?.*"), json=body
    )
    result = _datasets().history("uuid-1", event_type=AuditLogEventType.created, skip=5)
    assert isinstance(result, PaginatedResponse)
    assert isinstance(result.results[0], DatasetAuditLogResponse)
    params = httpx_mock.get_request().url.params
    assert params["skip"] == "5"
    assert params["event_type"] == "created"


def test_list_parents_parses(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}collections/col-1/parents.*"),
        json={"total": 1, "limit": 100, "offset": 0, "results": [COLLECTION_RESPONSE]},
    )
    result = _collections().list_parents("col-1")
    assert result.results[0].id == "col-1"


# --- Gap 4a: async parity for child-collection methods ---


async def test_async_add_and_remove_collection(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}collections/col-1/collections/col-2",
        method="PUT",
        json=COLLECTION_RESPONSE,
    )
    httpx_mock.add_response(
        url=f"{BASE}collections/col-1/collections/col-2",
        method="DELETE",
        status_code=204,
    )
    async with _async_collections() as client:
        added = await client.add_collection("col-1", "col-2")
        assert added.id == "col-1"
        assert await client.remove_collection("col-1", "col-2") is None


# --- Gap 4b + 6: async register dup handling + lineage metadata ---


def _registration_request_with_lineage():
    from catalog_client.models.asset import AssetType, DataAssetRequest
    from catalog_client.models.governance import GovernanceMetadata
    from catalog_client.models.metadata import DatasetMetadata
    from catalog_client.registration.request import LineageSpec, RegistrationRequest

    return RegistrationRequest(
        canonical_id="ds-001",
        name="Test",
        version="1.0.0",
        project="atlas",
        modality=DatasetModality.sequencing,
        locations=[
            DataAssetRequest(location_uri="s3://b/k", asset_type=AssetType.file)
        ],
        governance=GovernanceMetadata(),
        metadata=DatasetMetadata(),
        lineage=[
            LineageSpec(
                lineage_type=LineageType.transformed_from,
                source_dataset_id="src-1",
                metadata={"pipeline": "nf-core"},
            )
        ],
    )


def test_register_sends_lineage_metadata(httpx_mock: HTTPXMock):
    # dup-check list (empty), dataset create, lineage create
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}datasets/\?.*"),
        json={"total": 0, "limit": 10, "offset": 0, "results": []},
    )
    httpx_mock.add_response(
        url=f"{BASE}datasets/", method="POST", json=DATASET_RESPONSE
    )
    httpx_mock.add_response(
        url=f"{BASE}lineage/",
        method="POST",
        json={
            "id": "edge-1",
            "tombstoned": False,
            "created_at": "2024-01-01T00:00:00Z",
            "last_modified_at": "2024-01-01T00:00:00Z",
            "source_dataset_id": "src-1",
            "destination_dataset_id": "uuid-1",
            "source_data_asset_id": None,
            "destination_data_asset_id": None,
            "lineage_type": "transformed_from",
            "metadata": {"pipeline": "nf-core"},
        },
    )
    with CatalogClient(base_url="http://test.local", api_token=TOKEN) as client:
        client.register(_registration_request_with_lineage(), error_on_duplicate=False)
    lineage_req = [
        r for r in httpx_mock.get_requests() if r.url.path.endswith("/lineage/")
    ][0]
    assert json.loads(lineage_req.content)["metadata"] == {"pipeline": "nf-core"}


async def test_async_register_error_on_duplicate(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}datasets/\?.*"),
        json={"total": 1, "limit": 10, "offset": 0, "results": [DATASET_RESPONSE]},
    )
    async with AsyncCatalogClient(
        base_url="http://test.local", api_token=TOKEN
    ) as client:
        with pytest.raises(DuplicateDatasetError):
            await client.register(
                _registration_request_with_lineage(), error_on_duplicate=True
            )


# --- Gap 5a: project optional on the model ---


def test_dataset_request_allows_missing_project():
    req = DatasetRequest(
        canonical_id="c",
        name="n",
        modality=DatasetModality.imaging,
        governance={},
        metadata={},
        locations=[{"location_uri": "s3://b/k", "asset_type": "file"}],
    )
    assert req.project is None
