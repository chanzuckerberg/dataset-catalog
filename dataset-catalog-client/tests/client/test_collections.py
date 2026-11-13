import json
import re

import httpx
from pytest_httpx import HTTPXMock

from catalog_client.client.collections_ import AsyncCollectionClient, CollectionClient
from catalog_client.models.collection import (
    ChildCollectionEntryResponse,
    CollectionChildType,
    CollectionRequest,
    CollectionType,
    DatasetEntryResponse,
)
from catalog_client.models.pagination import PaginatedResponse

BASE = "http://test.local/api/v1/"

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

DATASET_RESPONSE = {
    "id": "ds-1",
    "tombstoned": False,
    "created_at": "2024-01-01T00:00:00Z",
    "last_modified_at": "2024-01-01T00:00:00Z",
    "canonical_id": "ds-001",
    "version": "1.0.0",
    "project": "atlas",
    "locations": [],
    "name": "Test Dataset",
    "modality": "imaging",
    "dataset_type": "raw",
    "governance": {"data_steward": "team-data", "is_pii": False, "is_phi": False},
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

DATASET_ENTRY = {"entry_type": "dataset", "entry": DATASET_RESPONSE}
COLLECTION_ENTRY = {"entry_type": "collection", "entry": COLLECTION_RESPONSE}

ENTRIES_URL = re.compile(rf"{re.escape(BASE)}collections/col-1/entries")

PAGINATED = {"total": 1, "limit": 100, "offset": 0, "results": [COLLECTION_RESPONSE]}

COLLECTIONS_URL = re.compile(rf"{re.escape(BASE)}collections/")


def _sync_client():
    return CollectionClient(httpx.Client(base_url=BASE))


def _async_client():
    return AsyncCollectionClient(httpx.AsyncClient(base_url=BASE))


def test_collection_type_enum():
    assert CollectionType.publication == "publication"
    assert CollectionType.training == "training"
    # Added in schema v1.6.0, giving the Study > Experiment hierarchy real values.
    assert CollectionType.study == "study"
    assert CollectionType.experiment == "experiment"


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
    httpx_mock.add_response(
        url=COLLECTIONS_URL, status_code=201, json=COLLECTION_RESPONSE
    )
    coll = CollectionRequest(
        canonical_id="col-001",
        version="1.0.0",
        name="My Collection",
        collection_owner="team-x",
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
        url=f"{BASE}collections/col-1/datasets/ds-1", method="DELETE", status_code=204
    )
    result = _sync_client().remove_dataset("col-1", "ds-1")
    assert result is None


def test_update_collection(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=f"{BASE}collections/col-1", json=COLLECTION_RESPONSE)
    coll = CollectionRequest(
        canonical_id="col-001",
        version="1.0.0",
        name="My Collection",
        collection_owner="team-x",
    )
    result = _sync_client().update("col-1", coll)
    assert result.id == "col-1"


def test_list_collections_with_canonical_id_filter(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=COLLECTIONS_URL, json=PAGINATED)
    result = _sync_client().list(canonical_id="col-001")
    assert result.results[0].canonical_id == "col-001"


def test_list_collections_with_version_filter(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=COLLECTIONS_URL, json=PAGINATED)
    result = _sync_client().list(version="1.0.0")
    assert result.results[0].version == "1.0.0"


def test_add_collection_to_collection(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}collections/col-1/collections/col-2", json=COLLECTION_RESPONSE
    )
    result = _sync_client().add_collection("col-1", "col-2")
    assert result.id == "col-1"


def test_remove_collection_from_collection(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}collections/col-1/collections/col-2",
        method="DELETE",
        status_code=204,
    )
    result = _sync_client().remove_collection("col-1", "col-2")
    assert result is None


async def test_list_collections_async(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=COLLECTIONS_URL, json=PAGINATED)
    async with _async_client() as client:
        result = await client.list()
    assert result.total == 1


# --- list_entries ---


def test_list_entries_mixed_types(httpx_mock: HTTPXMock):
    # Response contains one dataset entry and one child-collection entry.
    httpx_mock.add_response(
        url=ENTRIES_URL,
        json={
            "total": 2,
            "limit": 100,
            "offset": 0,
            "results": [DATASET_ENTRY, COLLECTION_ENTRY],
        },
    )
    result = _sync_client().list_entries("col-1")
    assert isinstance(result, PaginatedResponse)
    assert result.total == 2
    assert len(result.results) == 2
    assert isinstance(result.results[0], DatasetEntryResponse)
    assert result.results[0].entry.id == "ds-1"
    assert isinstance(result.results[1], ChildCollectionEntryResponse)
    assert result.results[1].entry.id == "col-1"


def test_list_entries_dataset_only(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=ENTRIES_URL,
        json={"total": 1, "limit": 100, "offset": 0, "results": [DATASET_ENTRY]},
    )
    result = _sync_client().list_entries("col-1")
    assert len(result.results) == 1
    assert isinstance(result.results[0], DatasetEntryResponse)
    assert result.results[0].entry_type == "dataset"
    assert result.results[0].entry.canonical_id == "ds-001"


def test_list_entries_pagination_fields_propagated(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=ENTRIES_URL,
        json={"total": 50, "limit": 10, "offset": 20, "results": [DATASET_ENTRY]},
    )
    result = _sync_client().list_entries("col-1", offset=20, limit=10)
    assert result.total == 50
    assert result.limit == 10
    assert result.offset == 20


def test_list_entries_emits_entry_type(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=ENTRIES_URL,
        json={"total": 0, "limit": 100, "offset": 0, "results": []},
    )
    _sync_client().list_entries("col-1", entry_type=CollectionChildType.dataset)
    assert httpx_mock.get_request().url.params["entry_type"] == "dataset"


# --- list_parents ---


def test_list_parents(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}collections/col-1/parents.*"),
        json=PAGINATED,
    )
    result = _sync_client().list_parents("col-1")
    assert isinstance(result, PaginatedResponse)
    assert result.results[0].id == "col-1"


# --- async child-collection parity ---


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
    async with _async_client() as client:
        added = await client.add_collection("col-1", "col-2")
        assert added.id == "col-1"
        await client.remove_collection("col-1", "col-2")


# --- Entry-level metadata ---


def test_add_dataset_sends_no_body_without_metadata(httpx_mock: HTTPXMock):
    """An omitted body is not an empty one: {} would clear existing metadata."""
    httpx_mock.add_response(
        url=f"{BASE}collections/col-1/datasets/ds-1", json=COLLECTION_RESPONSE
    )
    _sync_client().add_dataset("col-1", "ds-1")
    assert httpx_mock.get_request().content == b""


def test_add_dataset_sends_entry_metadata(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}collections/col-1/datasets/ds-1", json=COLLECTION_RESPONSE
    )
    _sync_client().add_dataset("col-1", "ds-1", metadata={"role": "train"})
    assert json.loads(httpx_mock.get_request().content) == {
        "metadata": {"role": "train"}
    }


def test_add_collection_sends_entry_metadata(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}collections/col-1/collections/col-2", json=COLLECTION_RESPONSE
    )
    _sync_client().add_collection("col-1", "col-2", metadata={"order": 2})
    assert json.loads(httpx_mock.get_request().content) == {"metadata": {"order": 2}}


def test_entries_parse_membership_fields(httpx_mock: HTTPXMock):
    entry = {
        **DATASET_ENTRY,
        "metadata": {"role": "train"},
        "created_at": "2024-02-01T00:00:00Z",
        "last_modified_at": "2024-02-02T00:00:00Z",
    }
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}collections/col-1/entries\?.*"),
        json={"total": 1, "limit": 100, "offset": 0, "results": [entry]},
    )
    page = _sync_client().list_entries("col-1")
    parsed = page.results[0]
    assert parsed.metadata == {"role": "train"}
    assert parsed.created_at.year == 2024
    assert parsed.last_modified_at.day == 2


def test_entries_tolerate_a_deployment_without_membership_fields(
    httpx_mock: HTTPXMock,
):
    """A client pinned ahead of the API still reads its collections."""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}collections/col-1/entries\?.*"),
        json={"total": 1, "limit": 100, "offset": 0, "results": [DATASET_ENTRY]},
    )
    parsed = _sync_client().list_entries("col-1").results[0]
    assert parsed.metadata == {}
    assert parsed.created_at is None


def test_entries_tolerate_a_null_metadata_column(httpx_mock: HTTPXMock):
    """A NULL JSONB column arrives as an explicit null, not an absent key."""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}collections/col-1/entries\?.*"),
        json={
            "total": 1,
            "limit": 100,
            "offset": 0,
            "results": [{**DATASET_ENTRY, "metadata": None}],
        },
    )
    assert _sync_client().list_entries("col-1").results[0].metadata == {}


async def test_async_add_dataset_sends_entry_metadata(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}collections/col-1/datasets/ds-1", json=COLLECTION_RESPONSE
    )
    async with _async_client() as client:
        await client.add_dataset("col-1", "ds-1", metadata={"role": "eval"})
    assert json.loads(httpx_mock.get_request().content) == {
        "metadata": {"role": "eval"}
    }
