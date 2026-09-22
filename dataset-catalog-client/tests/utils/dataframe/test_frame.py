"""The pandas layer."""

from __future__ import annotations

import builtins
import inspect
import warnings

import pytest
from pytest_httpx import HTTPXMock

from catalog_client.exceptions import CatalogUsageError
from catalog_client.utils.dataframe import ColumnSpec, iter_records, to_dataframe

from .conftest import dataset_dict, list_page

pd = pytest.importorskip("pandas")


def test_rows_become_a_dataframe(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        json=list_page([dataset_dict(id="uuid-1"), dataset_dict(id="uuid-2")])
    )

    df = to_dataframe(client, project="atlas")

    assert len(df) == 2
    assert list(df["id"]) == ["uuid-1", "uuid-2"]


def test_column_order_matches_the_request(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    df = to_dataframe(client, project="atlas", columns=["name", "id", "project"])

    assert list(df.columns) == ["name", "id", "project"]


def test_mapper_columns_are_appended_after_the_declarative_ones(
    client, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    df = to_dataframe(
        client,
        project="atlas",
        columns=["id"],
        mapper=lambda ds: {"derived": len(ds.locations)},
    )

    assert list(df.columns) == ["id", "derived"]
    assert df["derived"].iloc[0] == 2


def test_datetime_columns_get_a_datetime_dtype(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    df = to_dataframe(client, project="atlas", columns=["created_at"])

    assert pd.api.types.is_datetime64_any_dtype(df["created_at"])


def test_an_empty_result_still_carries_the_declarative_columns(
    client, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(json=list_page([]))

    df = to_dataframe(client, project="atlas", columns=["id", "name"])

    assert df.empty
    assert list(df.columns) == ["id", "name"]


def test_an_empty_result_honours_rename(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([]))

    df = to_dataframe(
        client, project="atlas", columns=["id"], rename={"id": "dataset_id"}
    )

    assert list(df.columns) == ["dataset_id"]


def test_aliases_name_the_frame_columns(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    df = to_dataframe(
        client,
        project="atlas",
        columns=[ColumnSpec("metadata.experiment.sub_modality", alias="technique")],
    )

    assert list(df.columns) == ["technique"]
    assert df["technique"].iloc[0] == "confocal"


def test_a_clear_error_when_pandas_is_missing(client, monkeypatch):
    real_import = builtins.__import__

    def no_pandas(name, *args, **kwargs):
        if name == "pandas":
            raise ImportError("No module named 'pandas'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pandas)

    with pytest.raises(CatalogUsageError, match=r"catalog-client\[dataframe\]"):
        to_dataframe(client, project="atlas")


def test_the_empty_column_warning_names_the_callers_line(client, httpx_mock: HTTPXMock):
    """to_dataframe sits a frame below iter_records and consumes the generator
    itself, so this is the path a fixed stacklevel gets wrong."""
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        to_dataframe(client, project="atlas", columns=["metadata.typo.here"])

    assert len(caught) == 1
    assert caught[0].filename == __file__


def test_the_page_size_warning_names_the_callers_line(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        to_dataframe(client, project="atlas", page_size=9999, columns=["id"])

    assert len(caught) == 1
    assert caught[0].filename == __file__
    assert httpx_mock.get_request().url.params["limit"] == "100"


def test_no_private_stacklevel_parameter_leaks_into_the_public_signature():
    """Attribution is resolved by walking the stack, not by threading an
    offset through the public API."""
    for entry_point in (to_dataframe, iter_records):
        assert not [
            name
            for name in inspect.signature(entry_point).parameters
            if name.startswith("_")
        ]
