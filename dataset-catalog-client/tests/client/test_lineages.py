import re

import httpx
from pytest_httpx import HTTPXMock

from catalog_client.client.lineages import AsyncLineageClient, LineageClient
from catalog_client.models.lineage import (
    LineageEdgeRequest,
    LineageType,
)
from catalog_client.models.pagination import PaginatedResponse

BASE = "http://test.local/api/"

EDGE_RESPONSE = {
    "id": "edge-1",
    "tombstoned": False,
    "created_at": "2024-01-01T00:00:00Z",
    "created_by": "user-1",
    "last_modified_at": "2024-01-01T00:00:00Z",
    "modified_by": None,
    "source_dataset_id": "src-uuid",
    "destination_dataset_id": "dst-uuid",
    "lineage_type": "transformed_from",
    "source_data_asset_id": None,
    "destination_data_asset_id": None,
    "lineage_metadata": None,
}

PAGINATED = {"total": 1, "limit": 100, "offset": 0, "results": [EDGE_RESPONSE]}

LINEAGE_URL = re.compile(rf"{re.escape(BASE)}lineage/")


def _sync_client():
    return LineageClient(httpx.Client(base_url=BASE))


def _async_client():
    return AsyncLineageClient(httpx.AsyncClient(base_url=BASE))


def test_list_lineage_edges(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=LINEAGE_URL, json=PAGINATED)
    result = _sync_client().list()
    assert isinstance(result, PaginatedResponse)
    assert result.results[0].id == "edge-1"


def test_get_lineage_edge(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=f"{BASE}lineage/edge-1", json=EDGE_RESPONSE)
    result = _sync_client().get("edge-1")
    assert result.lineage_type == LineageType.transformed_from


def test_create_lineage_edge(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=LINEAGE_URL, status_code=201, json=EDGE_RESPONSE)
    edge = LineageEdgeRequest(
        source_dataset_id="src-uuid",
        destination_dataset_id="dst-uuid",
        lineage_type=LineageType.transformed_from,
    )
    result = _sync_client().create(edge)
    assert result.id == "edge-1"


def test_delete_lineage_edge(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=f"{BASE}lineage/edge-1", status_code=204)
    result = _sync_client().delete("edge-1")
    assert result is None


async def test_list_lineage_edges_async(httpx_mock: HTTPXMock):
    httpx_mock.add_response(url=LINEAGE_URL, json=PAGINATED)
    async with _async_client() as client:
        result = await client.list()
    assert result.total == 1
