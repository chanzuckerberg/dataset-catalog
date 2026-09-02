import re

import httpx
import pytest
from pytest_httpx import HTTPXMock

from catalog_client.client.datasets import AsyncDatasetClient, DatasetClient
from catalog_client.exceptions import NotFoundError
from catalog_client.models.dataset import (
    AuditLogEventType,
    DatasetAuditLogResponse,
    DatasetListSortOption,
    DatasetModality,
    DatasetRef,
    DatasetResponse,
    DatasetSearchHit,
    DatasetSearchResponse,
)
from catalog_client.models.pagination import (
    CursorPaginatedResponse,
    PaginatedResponse,
)

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
    assert isinstance(result, CursorPaginatedResponse)
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
    hit = result.results[0]
    assert isinstance(hit, DatasetSearchHit)  # only hits carry a relevance score
    assert hit.score == 1.5
    assert result.facets is not None
    assert result.facets["modality"][0].count == 1
    params = httpx_mock.get_request().url.params
    assert params["q"] == "test"
    assert params["facets"] == "modality"
    assert params["modality"] == "sequencing"


# --- Pagination ---

SEARCH_URL = re.compile(rf"{re.escape(BASE)}datasets/search/\?.*")

SEARCH_HIT = {
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


def _search_page(next_cursor=None, hit=None):
    return {
        "total": 2,
        "limit": 1,
        "results": [hit or SEARCH_HIT],
        "next_cursor": next_cursor,
    }


def test_search_sends_cursor_and_never_offset(httpx_mock: HTTPXMock):
    """The search route dropped `offset`; sending it would silently page nowhere."""
    httpx_mock.add_response(url=SEARCH_URL, json=_search_page())
    result = _sync_client().search(q="test", cursor="cur-1", limit=25)
    params = httpx_mock.get_request().url.params
    assert params["cursor"] == "cur-1"
    assert "offset" not in params
    assert "sort" not in params
    assert result.next_cursor is None


def test_search_rejects_offset_keyword():
    with pytest.raises(TypeError):
        _sync_client().search(q="test", offset=10)  # type: ignore[call-arg]


def test_search_hydrate_sends_flag_and_parses_full_records(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=SEARCH_URL, json=_search_page(hit=DATASET_RESPONSE))
    result = _sync_client().search(q="test", hydrate=True, limit=100)
    assert httpx_mock.get_request().url.params["hydrate"] == "true"
    assert isinstance(result.results[0], DatasetResponse)


def test_search_hydrate_limit_is_capped_client_side():
    with pytest.raises(ValueError, match="hydrate=True"):
        _sync_client().search(q="test", hydrate=True, limit=500)


def test_search_fields_preserved_as_extras(httpx_mock: HTTPXMock):
    hit = dict(SEARCH_HIT, license="CC-BY-4.0")
    httpx_mock.add_response(url=SEARCH_URL, json=_search_page(hit=hit))
    result = _sync_client().search(q="test", fields=["license"])
    assert httpx_mock.get_request().url.params["fields"] == "license"
    assert isinstance(result.results[0], DatasetSearchHit)
    assert result.results[0].model_extra == {"license": "CC-BY-4.0"}


def test_iter_search_follows_cursors_to_exhaustion(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=SEARCH_URL, json=_search_page(next_cursor="cur-2"))
    httpx_mock.add_response(url=SEARCH_URL, json=_search_page(next_cursor=None))
    hits = list(_sync_client().iter_search(q="test", limit=1))
    assert len(hits) == 2
    requests = httpx_mock.get_requests()
    assert "cursor" not in requests[0].url.params
    assert requests[1].url.params["cursor"] == "cur-2"


def test_iter_search_rejects_caller_supplied_cursor():
    with pytest.raises(ValueError, match="manages the cursor"):
        list(_sync_client().iter_search(q="test", cursor="cur-1"))


def test_list_accepts_null_total_and_offset(httpx_mock: HTTPXMock):
    """include_total=False makes the server return total: null."""
    body = {
        "limit": 100,
        "results": [DATASET_RESPONSE],
        "total": None,
        "offset": None,
        "next_cursor": "cur-2",
    }
    httpx_mock.add_response(url=DATASETS_URL, json=body)
    result = _sync_client().list(include_total=False)
    assert result.total is None
    assert result.offset is None
    assert result.next_cursor == "cur-2"
    assert httpx_mock.get_request().url.params["include_total"] == "false"


def test_list_omits_offset_when_paging_by_cursor(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=DATASETS_URL, json=PAGINATED_RESPONSE)
    _sync_client().list(cursor="cur-1")
    params = httpx_mock.get_request().url.params
    assert params["cursor"] == "cur-1"
    assert "offset" not in params


def test_list_defaults_send_no_paging_or_sort_params(httpx_mock: HTTPXMock):
    """Unset sort is omitted so the server applies its own default."""
    httpx_mock.add_response(url=DATASETS_URL, json=PAGINATED_RESPONSE)
    _sync_client().list()
    params = httpx_mock.get_request().url.params
    assert "cursor" not in params
    assert "offset" not in params
    assert "sort" not in params


def test_list_rejects_cursor_and_offset_together():
    with pytest.raises(ValueError, match="mutually exclusive"):
        _sync_client().list(cursor="cur-1", offset=10)


def test_list_rejects_offset_beyond_max_depth():
    with pytest.raises(ValueError, match="exceeds the maximum of 10000"):
        _sync_client().list(offset=10_001)


def test_list_offset_error_points_at_the_cursor():
    """The message has to name the alternative, or it is just a wall."""
    with pytest.raises(ValueError, match="cursor"):
        _sync_client().list(offset=50_000)


def test_list_allows_offset_at_exactly_max_depth(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=DATASETS_URL, json=PAGINATED_RESPONSE)
    _sync_client().list(offset=10_000)
    assert httpx_mock.get_request().url.params["offset"] == "10000"


async def test_async_list_rejects_offset_beyond_max_depth():
    async with _async_client() as client:
        with pytest.raises(ValueError, match="exceeds the maximum"):
            await client.list(offset=10_001)


def test_list_still_supports_offset_paging(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=DATASETS_URL, json=PAGINATED_RESPONSE)
    _sync_client().list(offset=20, sort=DatasetListSortOption.newest)
    params = httpx_mock.get_request().url.params
    assert params["offset"] == "20"
    assert params["sort"] == "newest"


def test_iter_all_walks_pages(httpx_mock: HTTPXMock):
    page1 = {
        "limit": 1,
        "results": [DATASET_RESPONSE],
        "total": None,
        "next_cursor": "cur-2",
    }
    page2 = {"limit": 1, "results": [DATASET_RESPONSE], "total": None}
    httpx_mock.add_response(url=DATASETS_URL, json=page1)
    httpx_mock.add_response(url=DATASETS_URL, json=page2)
    datasets = list(_sync_client().iter_all(limit=1))
    assert len(datasets) == 2
    first = httpx_mock.get_requests()[0].url.params
    assert "sort" not in first
    assert first["include_total"] == "false"


async def test_async_iter_all_walks_pages(httpx_mock: HTTPXMock):
    page1 = {
        "limit": 1,
        "results": [DATASET_RESPONSE],
        "total": None,
        "next_cursor": "cur-2",
    }
    page2 = {"limit": 1, "results": [DATASET_RESPONSE], "total": None}
    httpx_mock.add_response(url=DATASETS_URL, json=page1)
    httpx_mock.add_response(url=DATASETS_URL, json=page2)
    async with _async_client() as client:
        datasets = [ds async for ds in client.iter_all(limit=1)]
    assert len(datasets) == 2
    assert httpx_mock.get_requests()[1].url.params["cursor"] == "cur-2"


async def test_async_iter_search_walks_pages(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=SEARCH_URL, json=_search_page(next_cursor="cur-2"))
    httpx_mock.add_response(url=SEARCH_URL, json=_search_page(next_cursor=None))
    async with _async_client() as client:
        hits = [hit async for hit in client.iter_search(q="test", limit=1)]
    assert len(hits) == 2


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
