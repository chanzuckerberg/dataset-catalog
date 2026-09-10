"""The mapper escape hatch."""

from __future__ import annotations

import warnings

import pytest
from pytest_httpx import HTTPXMock

from catalog_client.exceptions import CatalogUsageError
from catalog_client.utils.dataframe import iter_records
from catalog_client.utils.dataframe._flatten import flatten_record
from catalog_client.utils.dataframe._types import ColumnSpec

from .conftest import dataset_dict, dataset_model, list_page


def test_mapper_receives_the_model_not_a_dict():
    seen = []

    def mapper(dataset):
        seen.append(dataset)
        return {"ok": True}

    flatten_record(dataset_model(), [], mapper=mapper)

    assert seen[0].canonical_id == "ds-001"
    assert seen[0].metadata.sample.organism[0].label == "Homo sapiens"


def test_mapper_output_merges_over_extracted_columns():
    row = flatten_record(
        dataset_model(),
        [ColumnSpec("canonical_id")],
        mapper=lambda ds: {"extra": 1},
    )

    assert row == {"canonical_id": "ds-001", "extra": 1}


def test_mapper_wins_on_a_column_collision():
    row = flatten_record(
        dataset_model(),
        [ColumnSpec("canonical_id")],
        mapper=lambda ds: {"canonical_id": "overridden"},
    )

    assert row == {"canonical_id": "overridden"}


def test_empty_columns_gives_a_mapper_only_row():
    row = flatten_record(dataset_model(), [], mapper=lambda ds: {"only": "this"})

    assert row == {"only": "this"}


def test_returning_none_drops_the_row():
    assert flatten_record(dataset_model(), [], mapper=lambda ds: None) is None


def test_mapper_values_are_not_scalarized():
    row = flatten_record(
        dataset_model(),
        [ColumnSpec("metadata.sample.organism[].label", alias="declarative")],
        mapper=lambda ds: {"from_mapper": ["a", "b"]},
        list_sep="; ",
    )

    # The declarative column is joined; the mapper's list is left alone.
    assert row["declarative"] == "Homo sapiens; Mus musculus"
    assert row["from_mapper"] == ["a", "b"]


def test_rename_applies_to_mapper_keys():
    row = flatten_record(
        dataset_model(),
        [],
        mapper=lambda ds: {"raw": 1},
        rename={"raw": "pretty"},
    )

    assert row == {"pretty": 1}


def test_a_raising_mapper_names_the_dataset():
    def broken(dataset):
        raise AttributeError("'NoneType' object has no attribute 'channels'")

    with pytest.raises(CatalogUsageError) as excinfo:
        flatten_record(dataset_model(), [], mapper=broken)

    message = str(excinfo.value)
    assert "uuid-1" in message
    assert "AttributeError" in message
    assert isinstance(excinfo.value.__cause__, AttributeError)


def test_dropped_rows_do_not_reach_the_caller(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        json=list_page(
            [dataset_dict(id="uuid-1"), dataset_dict(id="uuid-2", project="other")]
        )
    )

    rows = list(
        iter_records(
            client,
            columns=["id"],
            mapper=lambda ds: None if ds.project == "other" else {},
        )
    )

    assert [row["id"] for row in rows] == ["uuid-1"]


def test_an_always_none_mapper_column_does_not_warn(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        list(
            iter_records(
                client,
                columns=["id"],
                mapper=lambda ds: {"never_set": None},
            )
        )

    assert caught == []


def test_columns_empty_and_no_mapper_is_rejected(client):
    with pytest.raises(CatalogUsageError, match="every row would be empty"):
        list(iter_records(client, columns=[]))
