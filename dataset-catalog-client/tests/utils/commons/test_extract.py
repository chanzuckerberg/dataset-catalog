"""Dot-path traversal — the syntax both the manifest and dataframe rely on.

Lives here rather than under either caller because it is shared: it used to
sit in the dataframe tests, where a dataframe refactor could have taken the
manifest's only coverage with it.
"""

from __future__ import annotations

import pytest

from catalog_client.utils.commons import extract_field, extract_path, parse_path

METADATA = {"sample": {"organism": [{"label": "Homo sapiens"}]}}


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
    assert extract_field(METADATA, path) == expected


@pytest.mark.parametrize(
    ("path", "segments"),
    [
        ("name", (("name", False, None),)),
        ("sample.organism[]", (("sample", False, None), ("organism", True, None))),
        ("dimension.0", (("dimension", False, None), ("0", False, 0))),
    ],
)
def test_parse_path_resolves_the_syntax_once(path, segments):
    """`[]` and positional indexes are decided at parse time, not per record."""
    assert parse_path(path) == segments


@pytest.mark.parametrize(
    "path",
    [
        "sample.organism[].label",
        "sample.organism.0.label",
        "sample.missing.deeper",
    ],
)
def test_the_two_entry_points_agree(path):
    """`extract_field` is the one-shot wrapper; it must not diverge from the
    parse-once path the dataframe walks."""
    assert extract_field(METADATA, path) == extract_path(METADATA, parse_path(path))
