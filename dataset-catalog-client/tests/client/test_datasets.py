import json
import re

import httpx
import pytest
from pydantic import ValidationError as PydanticValidationError
from pytest_httpx import HTTPXMock

from catalog_client.client.datasets import AsyncDatasetClient, DatasetClient
from catalog_client.exceptions import (
    CatalogError,
    CatalogServerError,
    CatalogUsageError,
    CopyError,
    NotFoundError,
)
from catalog_client.models.asset import AssetType, LocationScope, StoragePlatform
from catalog_client.models.copy import (
    CopyEntry,
    CopyErrorCode,
    CopyProvenance,
    CopyType,
    DatasetCopyRequest,
    DatasetCopyResponse,
)
from catalog_client.models.dataset import (
    AuditLogEventType,
    DatasetAuditLogResponse,
    DatasetListSortOption,
    DatasetModality,
    DatasetRef,
    DatasetResponse,
    DatasetSearchHit,
    DatasetSearchResponse,
    DatasetType,
)
from catalog_client.models.metadata import ObservationUnit
from catalog_client.models.pagination import (
    CursorPaginatedResponse,
    PaginatedResponse,
)

BASE = "http://test.local/api/v1/"
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
    "governance": {"data_steward": "team-data", "is_pii": False, "is_phi": False},
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


# --- Pagination guardrails ---


def test_hydrate_refuses_to_degrade_incomplete_records(httpx_mock: HTTPXMock):
    """A hydrated page must parse as full records or raise, never as hits.

    DatasetSearchHit allows extras and requires few fields, so validating
    against a union would silently accept a half-built DatasetResponse and
    hand back lightweight hits the caller never asked for.
    """
    partial = {k: v for k, v in DATASET_RESPONSE.items() if k != "governance"}
    httpx_mock.add_response(url=SEARCH_URL, json=_search_page(hit=partial))
    with pytest.raises(PydanticValidationError, match="governance"):
        _sync_client().search(q="test", hydrate=True)


def test_search_rejects_limit_above_route_ceiling():
    with pytest.raises(CatalogUsageError, match="limit must be <= 1000"):
        _sync_client().search(q="test", limit=1001)


def test_list_rejects_limit_above_route_ceiling():
    with pytest.raises(CatalogUsageError, match="limit must be <= 500"):
        _sync_client().list(limit=501)


@pytest.mark.parametrize("limit", [0, -1])
def test_limit_below_one_is_rejected(limit):
    with pytest.raises(CatalogUsageError, match="limit must be >= 1"):
        _sync_client().list(limit=limit)


def test_list_rejects_negative_offset():
    with pytest.raises(CatalogUsageError, match="offset must be >= 0"):
        _sync_client().list(offset=-1)


def test_guardrails_stay_catchable_as_value_error():
    """CatalogUsageError is a ValueError too, so pre-existing except arms hold."""
    with pytest.raises(ValueError):
        _sync_client().list(offset=10_001)


def test_iter_all_aborts_on_repeating_cursor(httpx_mock: HTTPXMock):
    """A server echoing its own cursor would otherwise loop forever."""
    page = {
        "limit": 1,
        "results": [DATASET_RESPONSE],
        "total": None,
        "next_cursor": "cur-stuck",
    }
    httpx_mock.add_response(url=DATASETS_URL, json=page, is_reusable=True)
    with pytest.raises(CatalogError, match="same cursor"):
        list(_sync_client().iter_all(limit=1))


def test_iter_search_aborts_on_empty_page_with_cursor(httpx_mock: HTTPXMock):
    body = {"total": 0, "limit": 1, "results": [], "next_cursor": "cur-2"}
    httpx_mock.add_response(url=SEARCH_URL, json=body)
    with pytest.raises(CatalogError, match="empty page"):
        list(_sync_client().iter_search(q="test", limit=1))


async def test_async_iter_all_aborts_on_repeating_cursor(httpx_mock: HTTPXMock):
    page = {
        "limit": 1,
        "results": [DATASET_RESPONSE],
        "total": None,
        "next_cursor": "cur-stuck",
    }
    httpx_mock.add_response(url=DATASETS_URL, json=page, is_reusable=True)
    async with _async_client() as client:
        with pytest.raises(CatalogError, match="same cursor"):
            [ds async for ds in client.iter_all(limit=1)]


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


# --- Resolve ---

RESOLVE_URL = re.compile(rf"{re.escape(BASE)}datasets/resolve\?.*")


def test_resolve_sends_uri_scope_and_platform(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=RESOLVE_URL,
        json={"total": 1, "limit": 50, "results": [DATASET_RESPONSE]},
    )
    page = _sync_client().resolve(
        "s3://bucket/proj/raw/f.h5ad",
        scope=LocationScope.ancestor,
        storage_platform=StoragePlatform.s3,
    )
    assert isinstance(page.results[0], DatasetResponse)
    params = httpx_mock.get_request().url.params
    assert params["uri"] == "s3://bucket/proj/raw/f.h5ad"
    assert params["scope"] == "ancestor"
    assert params["storage_platform"] == "s3"
    assert params["limit"] == "50"


def test_resolve_defaults_to_exact_and_omits_platform(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=RESOLVE_URL, json={"total": 0, "limit": 50, "results": []}
    )
    _sync_client().resolve("/hpc/projects/x/f.h5ad")
    params = httpx_mock.get_request().url.params
    assert params["scope"] == "exact"
    assert "storage_platform" not in params


def test_resolve_rejects_limit_above_route_ceiling():
    with pytest.raises(CatalogUsageError, match="<= 100"):
        _sync_client().resolve("s3://bucket/k", limit=101)


def test_iter_resolve_follows_cursor(httpx_mock: HTTPXMock):
    second = {**DATASET_RESPONSE, "id": "uuid-2"}
    httpx_mock.add_response(
        url=RESOLVE_URL,
        json={
            "total": 2,
            "limit": 1,
            "results": [DATASET_RESPONSE],
            "next_cursor": "cur-1",
        },
    )
    httpx_mock.add_response(
        url=RESOLVE_URL,
        json={"total": 2, "limit": 1, "results": [second], "next_cursor": None},
    )
    found = list(_sync_client().iter_resolve("s3://bucket/proj", limit=1))
    assert [record.id for record in found] == ["uuid-1", "uuid-2"]
    assert httpx_mock.get_requests()[1].url.params["cursor"] == "cur-1"


def test_iter_resolve_aborts_on_repeating_cursor(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=RESOLVE_URL,
        json={
            "total": 1,
            "limit": 1,
            "results": [DATASET_RESPONSE],
            "next_cursor": "cur-stuck",
        },
        is_reusable=True,
    )
    with pytest.raises(CatalogError, match="same cursor"):
        list(_sync_client().iter_resolve("s3://bucket/proj", limit=1))


async def test_async_resolve(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=RESOLVE_URL,
        json={"total": 1, "limit": 50, "results": [DATASET_RESPONSE]},
    )
    async with _async_client() as client:
        page = await client.resolve("s3://bucket/k", scope=LocationScope.descendant)
    assert page.results[0].id == "uuid-1"
    assert httpx_mock.get_request().url.params["scope"] == "descendant"


# --- Copy ---

COPY_URL = re.compile(rf"{re.escape(BASE)}datasets/uuid-1/copy\?.*")

COPY_REQUEST = DatasetCopyRequest(
    project="CryoET Data Portal",
    canonical_id="DS-10053",
    version="2.0.0",
    storage_platform=StoragePlatform.s3,
    root_uri="s3://czi-public/10053/",
    entries=[
        CopyEntry(
            location_uri="s3://czi-public/10053/tomogram.zarr",
            asset_type=AssetType.folder,
            storage_platform=StoragePlatform.s3,
            relative_path="tomogram.zarr",
            source_relative_path="tomogram.zarr",
        )
    ],
    lineage_metadata=CopyProvenance(hermes_job="job-8f21"),
)

COPY_RESPONSE = {
    "copy_type": "fork",
    "dataset_id": "uuid-copy",
    "project": "CryoET Data Portal",
    "canonical_id": "DS-10053",
    "version": "2.0.0",
    "lineage_edge_id": "edge-1",
}


def test_copy_sends_copy_type_as_query_param(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=COPY_URL, status_code=201, json=COPY_RESPONSE)
    result = _sync_client().copy("uuid-1", COPY_REQUEST, copy_type=CopyType.fork)
    assert isinstance(result, DatasetCopyResponse)
    assert result.model_dump(mode="json") == COPY_RESPONSE
    request = httpx_mock.get_request()
    assert request.url.params["copy_type"] == "fork"
    body = json.loads(request.content)
    assert body["root_uri"] == "s3://czi-public/10053/"
    assert body["entries"][0]["source_relative_path"] == "tomogram.zarr"
    assert body["lineage_metadata"]["hermes_job"] == "job-8f21"


def test_copy_replay_parses_the_200_the_same_way_as_the_201(httpx_mock: HTTPXMock):
    """A replay answers 200, not 201, and must still deserialize in full.

    The SDK does not surface which of the two it was, so this pins the
    parsing rather than the distinction: every field of the 201 body must
    come back identically off the 200.
    """
    httpx_mock.add_response(url=COPY_URL, status_code=200, json=COPY_RESPONSE)
    replayed = _sync_client().copy("uuid-1", COPY_REQUEST, copy_type=CopyType.fork)
    assert replayed.model_dump(mode="json") == COPY_RESPONSE


def test_copy_refusal_raises_copy_error_with_code(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=COPY_URL,
        status_code=409,
        json={
            "detail": {
                "code": "IDENTITY_TAKEN",
                "message": "already held by another dataset",
                "retryable": False,
            }
        },
    )
    with pytest.raises(CopyError) as excinfo:
        _sync_client().copy("uuid-1", COPY_REQUEST, copy_type=CopyType.fork)
    assert excinfo.value.code is CopyErrorCode.IDENTITY_TAKEN
    assert excinfo.value.retryable is False
    assert excinfo.value.status_code == 409


def test_copy_retryable_refusal_is_flagged(httpx_mock: HTTPXMock):
    """503 LINEAGE_WRITE_FAILED is the one refusal worth retrying."""
    httpx_mock.add_response(
        url=COPY_URL,
        status_code=503,
        json={
            "detail": {
                "code": "LINEAGE_WRITE_FAILED",
                "message": "nothing was written",
                "retryable": True,
            }
        },
    )
    with pytest.raises(CopyError) as excinfo:
        _sync_client().copy("uuid-1", COPY_REQUEST, copy_type=CopyType.fork)
    assert excinfo.value.retryable is True


def test_copy_error_keeps_an_unknown_code_as_a_string(httpx_mock: HTTPXMock):
    """A code this client predates still reaches the caller."""
    httpx_mock.add_response(
        url=COPY_URL,
        status_code=400,
        json={"detail": {"code": "FUTURE_CODE", "message": "x", "retryable": False}},
    )
    with pytest.raises(CopyError) as excinfo:
        _sync_client().copy("uuid-1", COPY_REQUEST, copy_type=CopyType.fork)
    assert excinfo.value.code == "FUTURE_CODE"


def test_copy_entry_forbids_unknown_fields():
    """A typo must fail here: exclude_none would drop it into a valid request."""
    with pytest.raises(PydanticValidationError):
        CopyEntry(
            location_uri="s3://czi-public/10053/tomogram.zarr",
            asset_type=AssetType.folder,
            storage_platform=StoragePlatform.s3,
            relative_path="tomogram.zarr",
            source_relative_pth="tomogram.zarr",
        )


def test_copy_request_forbids_unknown_fields():
    """extra='forbid' mirrors the server, so a stray key fails before the round trip."""
    with pytest.raises(PydanticValidationError):
        DatasetCopyRequest(
            **{**COPY_REQUEST.model_dump(), "governance": {"is_pii": False}}
        )


async def test_async_copy(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=COPY_URL, status_code=201, json=COPY_RESPONSE)
    async with _async_client() as client:
        result = await client.copy("uuid-1", COPY_REQUEST, copy_type=CopyType.mirror)
    assert result.dataset_id == "uuid-copy"
    assert httpx_mock.get_request().url.params["copy_type"] == "mirror"


def test_copy_404_is_also_a_not_found_error(httpx_mock: HTTPXMock):
    """A caller catching NotFoundError around a copy must still be reached."""
    httpx_mock.add_response(
        url=COPY_URL,
        status_code=404,
        json={
            "detail": {
                "code": "SOURCE_NOT_FOUND",
                "message": "does not exist or has been tombstoned",
                "retryable": False,
            }
        },
    )
    with pytest.raises(NotFoundError) as excinfo:
        _sync_client().copy("uuid-1", COPY_REQUEST, copy_type=CopyType.fork)
    assert isinstance(excinfo.value, CopyError)
    assert excinfo.value.code is CopyErrorCode.SOURCE_NOT_FOUND


def test_copy_503_is_also_a_server_error(httpx_mock: HTTPXMock):
    """LINEAGE_WRITE_FAILED is the one retryable refusal, so a retry wrapper
    built on CatalogServerError — as cli.py's is — has to catch it."""
    httpx_mock.add_response(
        url=COPY_URL,
        status_code=503,
        json={
            "detail": {
                "code": "LINEAGE_WRITE_FAILED",
                "message": "nothing was written",
                "retryable": True,
            }
        },
    )
    with pytest.raises(CatalogServerError) as excinfo:
        _sync_client().copy("uuid-1", COPY_REQUEST, copy_type=CopyType.fork)
    assert isinstance(excinfo.value, CopyError)
    assert excinfo.value.retryable is True


def test_copy_omits_provenance_keys_the_caller_never_set(httpx_mock: HTTPXMock):
    """lineage_metadata is stored on the edge verbatim, nulls included."""
    httpx_mock.add_response(url=COPY_URL, status_code=201, json=COPY_RESPONSE)
    _sync_client().copy("uuid-1", COPY_REQUEST, copy_type=CopyType.fork)
    body = json.loads(httpx_mock.get_request().content)
    assert body["lineage_metadata"] == {"hermes_job": "job-8f21"}
    assert "source_relative_path" in body["entries"][0]
    assert "encoding" not in body["entries"][0]


def test_search_sends_the_v170_filters(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}datasets/search/\?.*"),
        json={"total": 0, "limit": 10, "results": []},
    )
    _sync_client().search(
        dataset_type=DatasetType.analysis,
        observation_unit=ObservationUnit.pseudobulk,
        is_combined=False,
        uri_prefix="s3://bucket/proj",
    )
    params = httpx_mock.get_request().url.params
    assert params["dataset_type"] == "analysis"
    assert params["observation_unit"] == "pseudobulk"
    assert params["is_combined"] == "false"
    assert params["uri_prefix"] == "s3://bucket/proj"


def test_search_omits_the_v170_filters_when_unset(httpx_mock: HTTPXMock):
    """is_combined=False is a real filter; None must not send one."""
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}datasets/search/\?.*"),
        json={"total": 0, "limit": 10, "results": []},
    )
    _sync_client().search(q="x")
    params = httpx_mock.get_request().url.params
    for absent in ("dataset_type", "observation_unit", "is_combined", "uri_prefix"):
        assert absent not in params


def test_response_does_not_invent_a_schema_version(httpx_mock: HTTPXMock):
    """A deployment that omits the field must not read back as this client's default."""
    body = {k: v for k, v in DATASET_RESPONSE.items() if k != "record_schema_version"}
    httpx_mock.add_response(url=DATASETS_URL, json=body)
    assert _sync_client().get("uuid-1").record_schema_version is None


def test_copy_entry_is_a_data_asset_without_the_glob_fields():
    """CopyEntry shares DataAssetRequest's fields, but the copy route defines
    no include/exclude globs — inheriting them would send dead keys."""
    from catalog_client.models.asset import DataAssetRequest, _DataAssetBase

    assert issubclass(CopyEntry, _DataAssetBase)
    assert issubclass(DataAssetRequest, _DataAssetBase)
    shared = set(_DataAssetBase.model_fields)
    assert shared <= set(CopyEntry.model_fields)
    assert not shared & {"includes_pattern", "excludes_pattern"}
    assert "includes_pattern" not in CopyEntry.model_fields
    assert "excludes_pattern" not in CopyEntry.model_fields
