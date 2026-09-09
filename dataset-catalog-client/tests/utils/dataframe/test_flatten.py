"""Flattening a dataset record into a row — pure logic, no HTTP."""

from __future__ import annotations

import datetime

import pytest

from catalog_client.utils.commons import _extract_metadata_field
from catalog_client.utils.dataframe._columns import DEFAULT_COLUMNS, resolve_columns
from catalog_client.utils.dataframe._flatten import flatten_record
from catalog_client.utils.dataframe._types import ColumnSpec

from .conftest import dataset_model


def test_default_columns_produce_expected_row():
    row = flatten_record(dataset_model(), list(DEFAULT_COLUMNS))

    assert row is not None
    assert row["id"] == "uuid-1"
    assert row["canonical_id"] == "ds-001"
    assert row["project"] == "atlas"
    assert row["sub_modality"] == "confocal"
    assert row["license"] == "MIT"
    assert row["access_scope"] == "public"


def test_enum_values_are_unwrapped():
    row = flatten_record(dataset_model(), [ColumnSpec("modality")])

    assert row == {"modality": "imaging"}


def test_datetimes_stay_native_so_pandas_can_infer_the_dtype():
    row = flatten_record(dataset_model(), [ColumnSpec("created_at")])

    assert isinstance(row["created_at"], datetime.datetime)


def test_ontology_lists_are_joined():
    row = flatten_record(
        dataset_model(),
        [ColumnSpec("metadata.sample.organism[].label", alias="organism")],
    )

    assert row == {"organism": "Homo sapiens; Mus musculus"}


def test_list_sep_none_keeps_a_python_list():
    row = flatten_record(
        dataset_model(),
        [ColumnSpec("metadata.sample.organism[].label", alias="organism")],
        list_sep=None,
    )

    assert row == {"organism": ["Homo sapiens", "Mus musculus"]}


def test_deep_chain_through_a_list_of_objects():
    row = flatten_record(
        dataset_model(),
        [
            ColumnSpec(
                "metadata.data_summary.channels[].biological_annotation.marker",
                alias="markers",
            )
        ],
    )

    assert row == {"markers": "DAPI; GFP"}


def test_numeric_segment_indexes_into_a_list():
    row = flatten_record(
        dataset_model(),
        [ColumnSpec("metadata.data_summary.dimension.0", alias="width")],
    )

    assert row == {"width": 512}


def test_out_of_range_index_is_none_not_an_error():
    row = flatten_record(
        dataset_model(),
        [ColumnSpec("metadata.data_summary.dimension.9", alias="depth")],
    )

    assert row == {"depth": None}


def test_missing_path_resolves_to_none():
    row = flatten_record(dataset_model(), [ColumnSpec("metadata.nope.missing")])

    assert row == {"metadata.nope.missing": None}


def test_alias_names_the_column_and_path_is_the_fallback():
    row = flatten_record(
        dataset_model(),
        [ColumnSpec("governance.license"), ColumnSpec("governance.license", "lic")],
    )

    assert set(row) == {"governance.license", "lic"}


def test_rename_is_applied_to_output_names():
    row = flatten_record(
        dataset_model(),
        [ColumnSpec("canonical_id")],
        rename={"canonical_id": "dataset"},
    )

    assert row == {"dataset": "ds-001"}


def test_computed_columns_summarize_locations_without_adding_rows():
    row = flatten_record(
        dataset_model(),
        resolve_columns(["asset_count", "total_size_bytes"]),
    )

    assert row == {"asset_count": 2, "total_size_bytes": 350}


def test_total_size_bytes_is_none_when_no_asset_reports_one():
    record = dataset_model(
        locations=[{**location, "size_bytes": None} for location in _locations()]
    )
    row = flatten_record(record, resolve_columns(["total_size_bytes"]))

    assert row == {"total_size_bytes": None}


def _locations():
    return dataset_model().model_dump(mode="python")["locations"]


def test_plain_strings_are_promoted_to_column_specs():
    specs = resolve_columns(["canonical_id", ColumnSpec("name", "title")])

    assert [spec.column_name for spec in specs] == ["canonical_id", "title"]


def test_resolve_columns_none_selects_the_defaults():
    assert resolve_columns(None) == list(DEFAULT_COLUMNS)


def test_defaults_carry_no_locations_derived_column():
    names = {spec.column_name for spec in DEFAULT_COLUMNS}

    assert "asset_count" not in names
    assert "total_size_bytes" not in names
    assert not any(spec.path.startswith("locations") for spec in DEFAULT_COLUMNS)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("sample.organism[].label", ["Homo sapiens"]),
        ("sample.organism.0.label", "Homo sapiens"),
        ("sample.organism.0.nope", None),
        ("sample.organism.5", None),
        ("sample.organism.label", None),  # dict key against a list
        ("sample.missing.deeper", None),
        ("sample.organism[].missing", [None]),
    ],
)
def test_extractor_path_syntax(path, expected):
    metadata = {"sample": {"organism": [{"label": "Homo sapiens"}]}}

    assert _extract_metadata_field(metadata, path) == expected
