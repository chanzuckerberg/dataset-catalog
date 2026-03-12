import re

import httpx
import pytest
from pytest_httpx import HTTPXMock
from catalog_client.client.collections import AsyncCollectionClient, CollectionClient
from catalog_client.models.collection import CollectionCreate, CollectionResponse, CollectionUpdate
from catalog_client.models.pagination import PaginatedResponse

BASE = "http://test.local/api/"

COLLECTION_RESPONSE = {
    "id": "col-1",
    "tombstoned": False,
    "created_at": "2024-01-01T00:00:00Z",
    "created_by": "user-1",
    "last_modified_at": "2024-01-01T00:00:00Z",
    "modified_by": None,
    "canonical_id": "col-001",
    "version": "1.0.0",
    "name": "My Collection",
    "collection_owner": "team-x",
    "collection_metadata": None,
    "description": None,
    "license": None,
    "doi": None,
    "collection_type": None,
}

PAGINATED = {"total": 1, "limit": 100, "offset": 0, "results": [COLLECTION_RESPONSE]}

COLLECTIONS_URL = re.compile(rf"{re.escape(BASE)}collections/")


def _sync_client():
    return CollectionClient(httpx.Client(base_url=BASE))


def _async_client():
    return AsyncCollectionClient(httpx.AsyncClient(base_url=BASE))


def test_list_collections(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=COLLECTIONS_URL, json=PAGINATED)
    result = _sync_client().list()
    assert isinstance(result, PaginatedResponse)
    assert result.results[0].id == "col-1"


def test_get_collection(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=f"{BASE}collections/col-1", json=COLLECTION_RESPONSE)
    result = _sync_client().get("col-1")
    assert result.name == "My Collection"


def test_create_collection(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=COLLECTIONS_URL, status_code=201, json=COLLECTION_RESPONSE)
    coll = CollectionCreate(
        canonical_id="col-001", version="1.0.0", name="My Collection", collection_owner="team-x"
    )
    result = _sync_client().create(coll)
    assert result.id == "col-1"


def test_delete_collection(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=f"{BASE}collections/col-1", status_code=204)
    result = _sync_client().delete("col-1")
    assert result is None


def test_add_dataset_to_collection(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}collections/col-1/datasets/ds-1", json=COLLECTION_RESPONSE
    )
    result = _sync_client().add_dataset("col-1", "ds-1")
    assert result.id == "col-1"


def test_remove_dataset_from_collection(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}collections/col-1/datasets/ds-1", json=COLLECTION_RESPONSE
    )
    result = _sync_client().remove_dataset("col-1", "ds-1")
    assert result.id == "col-1"


async def test_list_collections_async(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=COLLECTIONS_URL, json=PAGINATED)
    async with _async_client() as client:
        result = await client.list()
    assert result.total == 1
