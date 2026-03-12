import re

import pytest
import httpx
from pytest_httpx import HTTPXMock
from catalog_client.client.datasets import DatasetClient, AsyncDatasetClient
from catalog_client.models.dataset import (
    DatasetCreate, DatasetModality, DatasetRef, DatasetResponse,
    DatasetUpdate, DatasetWithRelationsResponse,
)
from catalog_client.models.asset import AssetType, DataAssetRequest
from catalog_client.models.governance import GovernanceMetadata
from catalog_client.models.metadata import DatasetMetadata
from catalog_client.models.pagination import PaginatedResponse
from catalog_client.exceptions import NotFoundError

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
    "dataset_metadata": {},
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
        url=DATASETS_URL,
        json={"total": 0, "limit": 100, "offset": 0, "results": []}
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
