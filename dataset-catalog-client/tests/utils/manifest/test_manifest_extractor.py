"""Tests for metadata field extraction, exercised through the public generate_manifest API."""

from unittest.mock import MagicMock

import pytest

from catalog_client.utils.manifest import MetadataFieldSpec, generate_manifest

# ---------------------------------------------------------------------------
# Minimal client fixture
# ---------------------------------------------------------------------------


def _single_dataset_client(metadata):
    """Mock client containing one dataset whose metadata is *metadata*."""
    asset = MagicMock()
    asset.tombstoned = False
    asset.model_dump.return_value = {"location_uri": "s3://x"}

    dataset = MagicMock()
    dataset.id = "ds-1"
    dataset.canonical_id = "c-1"
    dataset.version = "1.0"
    dataset.record_version = 1
    dataset.tombstoned = False
    dataset.locations = [asset]
    dataset.metadata = MagicMock()
    dataset.metadata.model_dump.return_value = metadata

    entry = MagicMock()
    entry.entry_type = "dataset"
    entry.entry = dataset

    page = MagicMock()
    page.results = [entry]
    page.total = 1

    client = MagicMock()
    client.collections.list_entries.return_value = page
    return client


def _extract(path, metadata):
    """Run generate_manifest and return the extracted value for *path*."""
    result = generate_manifest(
        _single_dataset_client(metadata),
        "col-1",
        metadata_fields=[MetadataFieldSpec(path, alias="value")],
    )
    return result[0]["value"]


# ---------------------------------------------------------------------------
# Parametrized cases
# ---------------------------------------------------------------------------


@pytest.mark.filterwarnings("ignore::UserWarning")
@pytest.mark.parametrize(
    "path,metadata,expected",
    [
        # --- Flat and nested access ---
        ("split", {"split": "train"}, "train"),
        (
            "experiment.sub_modality",
            {"experiment": {"sub_modality": "confocal"}},
            "confocal",
        ),
        ("a.b.c", {"a": {"b": {"c": 42}}}, 42),
        # --- Value types ---
        ("count", {"count": 7}, 7),
        ("active", {"active": False}, False),
        # --- Missing / unreachable paths ---
        ("nonexistent", {}, None),
        ("a.b", {"a": {}}, None),
        ("a.b.c", {}, None),
        ("a.b", {"a": None}, None),
        ("a.b", {"a": "not-a-dict"}, None),
        ("field", {"field": None}, None),
        # --- List expansion ---
        (
            "organism[].label",
            {"organism": [{"label": "A"}, {"label": "B"}]},
            ["A", "B"],
        ),
        ("tags[]", {"tags": ["x", "y"]}, ["x", "y"]),
        ("items[]", {"items": []}, []),
        ("organism[].label", {"organism": "not-a-list"}, None),
        ("organism[].label", {}, None),
        (
            "items[].label",
            {"items": ["x", "y"]},
            [None, None],
        ),  # scalar items → None each
        ("sample.organism[].label", {"sample": {"organism": [{"label": "A"}]}}, ["A"]),
    ],
    ids=[
        "flat",
        "nested",
        "deep-nested",
        "int-value",
        "bool-false",
        "missing-top-key",
        "missing-nested-key",
        "missing-deep-key",
        "none-intermediate",
        "non-dict-intermediate",
        "explicit-none-value",
        "list-expand",
        "list-no-tail",
        "list-empty",
        "list-on-non-list",
        "list-key-absent",
        "list-scalar-items",
        "list-nested-prefix",
    ],
)
def test_metadata_extraction(path, metadata, expected):
    assert _extract(path, metadata) == expected
