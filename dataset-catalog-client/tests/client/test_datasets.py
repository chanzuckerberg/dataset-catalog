import re

import httpx
import pytest
from pytest_httpx import HTTPXMock

from catalog_client.client.datasets import AsyncDatasetClient, DatasetClient
from catalog_client.exceptions import NotFoundError
from catalog_client.models.dataset import (
    AuditLogEventType,
    DatasetAuditLogResponse,
    DatasetModality,
    DatasetRef,
    DatasetSearchResponse,
)
from catalog_client.models.pagination import PaginatedResponse

BASE = "http://test.local/api/"
TOKEN = "tok"

DATASET_RESPONSE = {
    "id": "uuid-1",
    "tombstoned": False,
    "created_at": "2024-01-01T00:00:00Z",
    "created_by": "user-1",
    "last_modified_at": "2024-01-01T00:00:00Z",
    "modified_by": None,
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
    "is_latest": False,
    "record_schema_version": None,
    "metadata_schema": None,
}

PAGINATED_RESPONSE = {
    "total": 1,
    "limit": 100,
    "offset": 0,
    "results": [DATASET_RESPONSE],
}

DATASETS_LIST_URL = re.compile(rf"{re.escape(BASE)}datasets/\?.*")
DATASETS_URL = re.compile(rf"{re.escape(BASE)}datasets/")


def _sync_client(httpx_mock=None):
    http = httpx.Client(base_url=BASE, headers={"X-catalog-api-token": TOKEN})
    return DatasetClient(http)


def _async_client():
    http = httpx.AsyncClient(base_url=BASE, headers={"X-catalog-api-token": TOKEN})
    return AsyncDatasetClient(http)


# --- Sync tests ---


def test_list_datasets(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=DATASETS_URL, json=PAGINATED_RESPONSE)
    client = _sync_client()
    result = client.list()
    assert isinstance(result, PaginatedResponse)
    assert result.total == 1
    assert result.results[0].id == "uuid-1"


def test_get_dataset_by_id(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=f"{BASE}datasets/uuid-1", json=DATASET_RESPONSE)
    client = _sync_client()
    result = client.get("uuid-1")
    assert result.id == "uuid-1"


def test_get_dataset_by_ref_resolves_uuid(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=DATASETS_URL, json=PAGINATED_RESPONSE)
    httpx_mock.add_response(url=f"{BASE}datasets/uuid-1", json=DATASET_RESPONSE)
    client = _sync_client()
    ref = DatasetRef(canonical_id="ds-001", version="1.0.0", project="atlas")
    result = client.get(ref)
    assert result.id == "uuid-1"


def test_get_dataset_ref_not_found_raises(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=DATASETS_URL, json={"total": 0, "limit": 100, "offset": 0, "results": []}
    )
    client = _sync_client()
    ref = DatasetRef("missing", "1.0.0", "proj")
    with pytest.raises(NotFoundError):
        client.get(ref)


def test_delete_dataset(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=f"{BASE}datasets/uuid-1", status_code=204)
    client = _sync_client()
    result = client.delete("uuid-1")
    assert result is None


# --- Async tests ---


async def test_list_datasets_async(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=DATASETS_URL, json=PAGINATED_RESPONSE)
    async with _async_client() as client:
        result = await client.list()
    assert result.total == 1


async def test_get_dataset_async(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=f"{BASE}datasets/uuid-1", json=DATASET_RESPONSE)
    async with _async_client() as client:
        result = await client.get("uuid-1")
    assert result.id == "uuid-1"


# --- Query params ---


def test_list_emits_access_scope_and_exclude_tombstoned(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=DATASETS_LIST_URL,
        json={"total": 0, "limit": 100, "offset": 0, "results": []},
    )
    _sync_client().list(access_scope="public", exclude_tombstoned=False)
    params = httpx_mock.get_request().url.params
    assert params["access_scope"] == "public"
    assert params["exclude_tombstoned"] == "false"


def test_get_emits_exclude_tombstoned_only_when_false(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}datasets/uuid-1.*"), json=DATASET_RESPONSE
    )
    _sync_client().get("uuid-1", exclude_tombstoned=False)
    assert httpx_mock.get_request().url.params["exclude_tombstoned"] == "false"


async def test_async_resolve_uses_limit_within_max(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=DATASETS_LIST_URL, json=PAGINATED_RESPONSE)
    httpx_mock.add_response(url=f"{BASE}datasets/uuid-1", json=DATASET_RESPONSE)
    async with _async_client() as client:
        await client.get(DatasetRef("ds-001", "1.0.0", "atlas"))
    list_req = httpx_mock.get_requests()[0]
    assert int(list_req.url.params["limit"]) <= 100


# --- Search ---


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
    result = _sync_client().search(
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


# --- History ---


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
    result = _sync_client().history(
        "uuid-1", event_type=AuditLogEventType.created, skip=5
    )
    assert isinstance(result, PaginatedResponse)
    assert isinstance(result.results[0], DatasetAuditLogResponse)
    params = httpx_mock.get_request().url.params
    assert params["skip"] == "5"
    assert params["event_type"] == "created"
