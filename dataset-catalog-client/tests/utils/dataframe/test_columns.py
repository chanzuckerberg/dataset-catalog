"""Column selection, opt-in computed columns, and the empty-column warning."""

from __future__ import annotations

import warnings

import pytest
from pytest_httpx import HTTPXMock

from catalog_client.utils.dataframe import DEFAULT_COLUMNS, ColumnSpec, iter_records

from .conftest import dataset_dict, list_page


def test_default_frame_has_no_locations_derived_column(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    row = next(iter(iter_records(client, project="atlas")))

    assert "asset_count" not in row
    assert "total_size_bytes" not in row
    assert "locations" not in row


def test_computed_columns_resolve_when_opted_into(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    row = next(
        iter(
            iter_records(
                client,
                project="atlas",
                columns=[*DEFAULT_COLUMNS, "asset_count", "total_size_bytes"],
            )
        )
    )

    assert row["asset_count"] == 2
    assert row["total_size_bytes"] == 350
    assert row["canonical_id"] == "ds-001"


def test_columns_are_emitted_in_the_requested_order(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    row = next(
        iter(iter_records(client, project="atlas", columns=["name", "id", "project"]))
    )

    assert list(row) == ["name", "id", "project"]


def test_a_column_that_is_none_everywhere_warns(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    with pytest.warns(UserWarning, match="metadata.typo.here"):
        list(
            iter_records(client, project="atlas", columns=["id", "metadata.typo.here"])
        )


def test_the_warning_reports_the_renamed_output_name(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    with pytest.warns(UserWarning, match="output 'oops'"):
        list(
            iter_records(
                client,
                project="atlas",
                columns=[ColumnSpec("metadata.typo.here", alias="typo")],
                rename={"typo": "oops"},
            )
        )


def test_a_column_set_in_only_some_rows_does_not_warn(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        json=list_page(
            [dataset_dict(id="uuid-1", doi=None), dataset_dict(id="uuid-2", doi="10.x")]
        )
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        list(iter_records(client, project="atlas", columns=["id", "doi"]))

    assert caught == []


def test_no_warning_when_there_are_no_rows(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([]))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        list(iter_records(client, project="atlas", columns=["metadata.typo.here"]))

    # Nothing came back, so an all-None column says nothing about the path.
    assert caught == []
