"""Column selection, opt-in computed columns, and the empty-column warning."""

from __future__ import annotations

import warnings

import pytest
from pytest_httpx import HTTPXMock

from catalog_client.exceptions import CatalogUsageError
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


def test_a_bare_string_of_columns_is_rejected(client):
    """`columns="x"` is a Sequence[str], so nothing but an explicit check
    stops it iterating into one column per character."""
    with pytest.raises(CatalogUsageError, match="bare string 'canonical_id'"):
        iter_records(client, project="atlas", columns="canonical_id")


def test_the_empty_column_warning_names_the_callers_line(client, httpx_mock: HTTPXMock):
    """Attribution has to survive being raised from inside a generator."""
    httpx_mock.add_response(json=list_page([dataset_dict()]))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        list(iter_records(client, project="atlas", columns=["metadata.typo.here"]))

    assert len(caught) == 1
    assert caught[0].filename == __file__


def test_attribution_survives_any_consumption_pattern(client, httpx_mock: HTTPXMock):
    """The warning fires as the generator finishes, so it is attributed to
    whoever resumed it — which differs per spelling.

    The sharper guard is the to_dataframe case in test_frame.py, where the
    resumer is library code; these three only pin that consuming iter_records
    directly never points into catalog_client.
    """
    for _ in range(3):
        httpx_mock.add_response(json=list_page([dataset_dict()]), is_reusable=True)

    def via_list():
        list(iter_records(client, project="atlas", columns=["metadata.typo.here"]))

    def via_for_loop():
        for _row in iter_records(
            client, project="atlas", columns=["metadata.typo.here"]
        ):
            pass

    def via_comprehension():
        [
            _row
            for _row in iter_records(
                client, project="atlas", columns=["metadata.typo.here"]
            )
        ]

    for consume in (via_list, via_for_loop, via_comprehension):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            consume()

        assert len(caught) == 1, consume.__name__
        assert caught[0].filename == __file__, consume.__name__
        assert "catalog_client" not in caught[0].filename, consume.__name__


@pytest.mark.parametrize(
    "bad, expected_type",
    [(1, "int"), (None, "NoneType"), (["nested"], "list")],
)
def test_a_non_path_column_entry_is_rejected(client, bad, expected_type):
    """str(column) would have produced a column named "1" or "None"."""
    with pytest.raises(CatalogUsageError, match=rf"columns\[1\].*{expected_type}"):
        iter_records(client, project="atlas", columns=["canonical_id", bad])


def test_a_dict_of_columns_is_rejected(client):
    """Iterating a dict yields its keys, which are valid paths — so only a
    non-sequence check catches it (probably meant `rename`)."""
    with pytest.raises(CatalogUsageError, match="list or tuple, got dict"):
        iter_records(client, project="atlas", columns={"organism": "label"})


def test_a_generator_of_columns_is_rejected(client):
    """to_dataframe resolves the names twice — once to extract, once to state
    the schema of a zero-row frame — so a one-shot iterator would silently
    come back empty the second time."""
    with pytest.raises(CatalogUsageError, match="list or tuple, got generator"):
        iter_records(client, project="atlas", columns=(c for c in ["id"]))
