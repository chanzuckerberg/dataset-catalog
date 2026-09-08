"""Which HTTP route the filters select, and what gets sent."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from catalog_client.exceptions import CatalogUsageError
from catalog_client.models.dataset import (
    DatasetListSortOption,
    DatasetModality,
    DatasetSortOption,
)
from catalog_client.utils.dataframe import iter_records

from .conftest import API, dataset_dict, list_page, search_page


def _paths(httpx_mock: HTTPXMock) -> list[str]:
    return [request.url.path for request in httpx_mock.get_requests()]


def test_project_only_uses_the_list_route(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    rows = list(iter_records(client, project="atlas"))

    assert len(rows) == 1
    request = httpx_mock.get_request()
    assert request.url.path == "/api/datasets/"
    assert request.url.params["project"] == "atlas"
    assert "/api/datasets/search/" not in _paths(httpx_mock)


def test_a_search_only_filter_uses_the_hydrated_search_route(
    client, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(json=search_page([dataset_dict()]))

    rows = list(iter_records(client, organism="Homo sapiens"))

    assert len(rows) == 1
    request = httpx_mock.get_request()
    assert request.url.path == "/api/datasets/search/"
    assert request.url.params["organism"] == "Homo sapiens"
    assert request.url.params["hydrate"] == "true"


def test_shared_filters_are_forwarded_on_the_search_route(
    client, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(json=search_page([dataset_dict()]))

    list(
        iter_records(
            client,
            q="liver",
            project="atlas",
            modality=DatasetModality.imaging,
            is_latest=True,
        )
    )

    params = httpx_mock.get_request().url.params
    assert params["q"] == "liver"
    assert params["project"] == "atlas"
    assert params["modality"] == "imaging"
    assert params["is_latest"] == "true"


def test_version_is_pushed_down_on_the_list_route(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    list(iter_records(client, project="atlas", version="1.0.0"))

    assert httpx_mock.get_request().url.params["version"] == "1.0.0"


def test_version_is_filtered_client_side_on_the_search_route(
    client, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(
        json=search_page(
            [
                dataset_dict(id="uuid-1", version="1.0.0"),
                dataset_dict(id="uuid-2", version="2.0.0"),
            ]
        )
    )

    rows = list(iter_records(client, organism="Homo sapiens", version="2.0.0"))

    # The server cannot express this filter, so both came back and one was dropped.
    assert [row["id"] for row in rows] == ["uuid-2"]
    assert "version" not in httpx_mock.get_request().url.params


def test_tombstoned_records_are_dropped_on_the_search_route(
    client, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(
        json=search_page(
            [
                dataset_dict(id="uuid-1", tombstoned=True),
                dataset_dict(id="uuid-2", tombstoned=False),
            ]
        )
    )

    rows = list(iter_records(client, organism="Homo sapiens"))

    assert [row["id"] for row in rows] == ["uuid-2"]


def test_exclude_tombstoned_false_keeps_them(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        json=search_page([dataset_dict(id="uuid-1", tombstoned=True)])
    )

    rows = list(iter_records(client, organism="Homo sapiens", exclude_tombstoned=False))

    assert [row["id"] for row in rows] == ["uuid-1"]


def test_canonical_id_is_not_a_supported_filter(client):
    with pytest.raises(TypeError, match="canonical_id"):
        list(iter_records(client, canonical_id="ds-001"))


def test_cursor_walk_follows_next_cursor_until_exhausted(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        json=list_page([dataset_dict(id="uuid-1")], next_cursor="c1")
    )
    httpx_mock.add_response(json=list_page([dataset_dict(id="uuid-2")]))

    rows = list(iter_records(client, project="atlas"))

    assert [row["id"] for row in rows] == ["uuid-1", "uuid-2"]
    assert httpx_mock.get_requests()[1].url.params["cursor"] == "c1"


def test_limit_stops_the_walk_without_fetching_the_next_page(
    client, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(
        json=list_page(
            [dataset_dict(id="uuid-1"), dataset_dict(id="uuid-2")],
            next_cursor="c1",
        )
    )

    rows = list(iter_records(client, project="atlas", limit=1))

    assert [row["id"] for row in rows] == ["uuid-1"]
    assert len(httpx_mock.get_requests()) == 1


def test_limit_zero_makes_no_request_at_all(client, httpx_mock: HTTPXMock):
    assert list(iter_records(client, project="atlas", limit=0)) == []
    assert httpx_mock.get_requests() == []


def test_negative_limit_is_rejected(client):
    with pytest.raises(CatalogUsageError, match="limit must be >= 0"):
        list(iter_records(client, project="atlas", limit=-1))


def test_page_size_is_forwarded_as_the_request_limit(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    list(iter_records(client, project="atlas", page_size=25))

    assert httpx_mock.get_request().url.params["limit"] == "25"


def test_page_size_is_capped_at_100_on_the_search_route(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=search_page([dataset_dict()]))

    with pytest.warns(UserWarning, match="capping at 100"):
        list(iter_records(client, organism="Homo sapiens", page_size=500))

    assert httpx_mock.get_request().url.params["limit"] == "100"


def test_page_size_is_capped_at_500_on_the_list_route(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    with pytest.warns(UserWarning, match="capping at 500"):
        list(iter_records(client, project="atlas", page_size=1000))

    assert httpx_mock.get_request().url.params["limit"] == "500"


def test_page_size_below_one_is_rejected(client):
    with pytest.raises(CatalogUsageError, match="page_size must be >= 1"):
        list(iter_records(client, project="atlas", page_size=0))


def test_list_sort_is_forwarded(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    list(iter_records(client, project="atlas", sort=DatasetListSortOption.newest))

    assert httpx_mock.get_request().url.params["sort"] == "newest"


def test_search_only_sort_on_the_list_route_is_rejected(client):
    with pytest.raises(CatalogUsageError, match="only supported by the search route"):
        list(iter_records(client, project="atlas", sort=DatasetSortOption.relevance))


def test_search_only_sort_is_fine_on_the_search_route(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=search_page([dataset_dict()]))

    list(iter_records(client, q="liver", sort=DatasetSortOption.relevance))

    assert httpx_mock.get_request().url.params["sort"] == "relevance"


def test_a_list_sort_widens_onto_the_search_route(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=search_page([dataset_dict()]))

    list(iter_records(client, q="liver", sort=DatasetListSortOption.newest))

    assert httpx_mock.get_request().url.params["sort"] == "newest"


def test_no_filters_walks_everything_via_the_list_route(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    list(iter_records(client))

    request = httpx_mock.get_request()
    assert request.url.path == "/api/datasets/"
    assert "project" not in request.url.params


def test_empty_result_yields_no_rows(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([]))

    assert list(iter_records(client, project="atlas")) == []


def test_url_is_the_expected_api_base(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    list(iter_records(client, project="atlas"))

    assert str(httpx_mock.get_request().url).startswith(API)
