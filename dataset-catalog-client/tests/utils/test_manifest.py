"""Unit tests for the public manifest generation API."""

from unittest.mock import MagicMock

import pytest

from catalog_client.utils.manifest import (
    ManifestResult,
    MetadataFieldSpec,
    generate_manifest,
    generate_manifest_iter,
)

# ---------------------------------------------------------------------------
# Helpers — build mock API objects
# ---------------------------------------------------------------------------


def _asset(
    location_uri="s3://bucket/file.tiff",
    storage_platform="s3",
    asset_type="file",
    checksum="abc123",
    checksum_alg="blake3",
    tombstoned=False,
):
    a = MagicMock()
    a.location_uri = location_uri
    a.checksum = checksum
    a.checksum_alg = checksum_alg
    a.tombstoned = tombstoned
    a.model_dump.return_value = {
        "location_uri": location_uri,
        "storage_platform": storage_platform,
        "asset_type": asset_type,
        "checksum": checksum,
        "checksum_alg": checksum_alg,
        "tombstoned": tombstoned,
    }
    return a


def _dataset(
    id="ds-1",
    canonical_id="ds-001",
    version="1.0.0",
    record_version=1,
    tombstoned=False,
    metadata=None,
    assets=(),
):
    d = MagicMock()
    d.id = id
    d.canonical_id = canonical_id
    d.version = version
    d.record_version = record_version
    d.tombstoned = tombstoned
    d.locations = list(assets)
    if metadata is not None:
        d.metadata = MagicMock()
        d.metadata.model_dump.return_value = metadata
    else:
        d.metadata = None
    return d


def _dataset_entry(dataset):
    e = MagicMock()
    e.entry_type = "dataset"
    e.entry = dataset
    return e


def _collection_entry(collection_id):
    e = MagicMock()
    e.entry_type = "collection"
    e.entry = MagicMock()
    e.entry.id = collection_id
    return e


def _page(entries, total=None):
    p = MagicMock()
    p.results = entries
    p.total = len(entries) if total is None else total
    return p


def _client(*pages):
    """Mock client whose list_entries returns each page in sequence."""
    c = MagicMock()
    c.collections.list_entries.side_effect = list(pages)
    return c


# ---------------------------------------------------------------------------
# Core row structure
# ---------------------------------------------------------------------------


def test_returns_manifest_result():
    client = _client(_page([_dataset_entry(_dataset(assets=[_asset()]))]))
    result = generate_manifest(client, "col-1")
    assert isinstance(result, ManifestResult)


def test_row_contains_fixed_dataset_and_asset_fields():
    client = _client(_page([_dataset_entry(_dataset(assets=[_asset()]))]))
    row = generate_manifest(client, "col-1")[0]

    assert row["dataset_id"] == "ds-1"
    assert row["canonical_id"] == "ds-001"
    assert row["version"] == "1.0.0"
    assert row["record_version"] == 1
    assert row["location_uri"] == "s3://bucket/file.tiff"
    assert row["storage_platform"] == "s3"
    assert row["checksum"] == "abc123"
    assert row["checksum_alg"] == "blake3"


def test_one_row_per_asset():
    dataset = _dataset(assets=[_asset("s3://a"), _asset("s3://b")])
    client = _client(_page([_dataset_entry(dataset)]))

    result = generate_manifest(client, "col-1")

    assert result.stats.total_rows == 2
    uris = {r["location_uri"] for r in result}
    assert uris == {"s3://a", "s3://b"}


def test_empty_collection_returns_empty_result():
    result = generate_manifest(_client(_page([])), "col-1")

    assert not result
    assert result.stats.total_datasets == 0
    assert result.stats.total_rows == 0


# ---------------------------------------------------------------------------
# Metadata fields
# ---------------------------------------------------------------------------


def test_metadata_field_with_alias():
    dataset = _dataset(
        assets=[_asset()],
        metadata={"experiment": {"sub_modality": "confocal"}},
    )
    client = _client(_page([_dataset_entry(dataset)]))

    result = generate_manifest(
        client,
        "col-1",
        metadata_fields=[
            MetadataFieldSpec("experiment.sub_modality", alias="modality")
        ],
    )

    assert result[0]["modality"] == "confocal"
    assert "experiment.sub_modality" not in result[0]


def test_metadata_field_without_alias_uses_path_as_key():
    dataset = _dataset(assets=[_asset()], metadata={"split": "train"})
    client = _client(_page([_dataset_entry(dataset)]))

    result = generate_manifest(
        client,
        "col-1",
        metadata_fields=[MetadataFieldSpec("split")],
    )

    assert result[0]["split"] == "train"


def test_metadata_list_expansion():
    dataset = _dataset(
        assets=[_asset()],
        metadata={
            "sample": {
                "organism": [{"label": "Homo sapiens"}, {"label": "Mus musculus"}]
            }
        },
    )
    client = _client(_page([_dataset_entry(dataset)]))

    result = generate_manifest(
        client,
        "col-1",
        metadata_fields=[
            MetadataFieldSpec("sample.organism[].label", alias="organisms")
        ],
    )

    assert result[0]["organisms"] == ["Homo sapiens", "Mus musculus"]


def test_missing_metadata_path_resolves_to_none():
    dataset = _dataset(assets=[_asset()], metadata={})
    client = _client(_page([_dataset_entry(dataset)]))

    result = generate_manifest(
        client,
        "col-1",
        metadata_fields=[MetadataFieldSpec("nonexistent.field", alias="x")],
    )

    assert result[0]["x"] is None


def test_warns_when_metadata_field_always_none():
    dataset = _dataset(assets=[_asset()], metadata={})
    client = _client(_page([_dataset_entry(dataset)]))

    with pytest.warns(UserWarning, match="bad.path"):
        generate_manifest(
            client,
            "col-1",
            metadata_fields=[MetadataFieldSpec("bad.path", alias="col")],
        )


# ---------------------------------------------------------------------------
# Filter condition
# ---------------------------------------------------------------------------


def test_filter_excludes_non_matching_assets():
    dataset = _dataset(
        assets=[
            _asset("s3://a.tiff", asset_type="file"),
            _asset("s3://b.csv", asset_type="file"),
        ]
    )
    client = _client(_page([_dataset_entry(dataset)]))

    result = generate_manifest(
        client,
        "col-1",
        filter_condition={"location_uri": {"endswith_": ".tiff"}},
    )

    assert result.stats.total_rows == 1
    assert result.stats.skipped_filtered_assets == 1
    assert result[0]["location_uri"] == "s3://a.tiff"


def test_filter_in_operator():
    dataset = _dataset(
        assets=[
            _asset(storage_platform="s3"),
            _asset(storage_platform="local"),
        ]
    )
    client = _client(_page([_dataset_entry(dataset)]))

    result = generate_manifest(
        client,
        "col-1",
        filter_condition={"storage_platform": {"in_": ["s3", "gcs"]}},
    )

    assert result.stats.total_rows == 1
    assert result[0]["storage_platform"] == "s3"


def test_filter_nin_operator():
    dataset = _dataset(
        assets=[
            _asset(asset_type="file"),
            _asset(asset_type="folder"),
        ]
    )
    client = _client(_page([_dataset_entry(dataset)]))

    result = generate_manifest(
        client,
        "col-1",
        filter_condition={"asset_type": {"nin_": ["folder"]}},
    )

    assert result.stats.total_rows == 1
    assert result.stats.skipped_filtered_assets == 1


def test_filter_eq_operator():
    dataset = _dataset(
        assets=[
            _asset(storage_platform="s3"),
            _asset(storage_platform="gcs"),
        ]
    )
    client = _client(_page([_dataset_entry(dataset)]))

    result = generate_manifest(
        client,
        "col-1",
        filter_condition={"storage_platform": {"eq_": "s3"}},
    )

    assert result.stats.total_rows == 1


def test_unknown_filter_operator_raises():
    dataset = _dataset(assets=[_asset()])
    client = _client(_page([_dataset_entry(dataset)]))

    with pytest.raises(ValueError, match="Unknown filter operator"):
        generate_manifest(
            client,
            "col-1",
            filter_condition={"location_uri": {"bad_op": "x"}},
        )


# ---------------------------------------------------------------------------
# Tombstone exclusion
# ---------------------------------------------------------------------------


def test_tombstoned_dataset_excluded_by_default():
    entries = [
        _dataset_entry(_dataset(id="ds-live", assets=[_asset()])),
        _dataset_entry(_dataset(id="ds-dead", tombstoned=True, assets=[_asset()])),
    ]
    client = _client(_page(entries))

    result = generate_manifest(client, "col-1")

    assert result.stats.total_datasets == 2
    assert result.stats.skipped_tombstoned_datasets == 1
    assert result.stats.total_rows == 1


def test_tombstoned_asset_excluded_by_default():
    dataset = _dataset(assets=[_asset(), _asset(tombstoned=True)])
    client = _client(_page([_dataset_entry(dataset)]))

    result = generate_manifest(client, "col-1")

    assert result.stats.skipped_tombstoned_assets == 1
    assert result.stats.total_rows == 1


def test_exclude_tombstoned_false_includes_all():
    client = _client(
        _page(
            [
                _dataset_entry(
                    _dataset(tombstoned=True, assets=[_asset(tombstoned=True)])
                )
            ]
        )
    )

    result = generate_manifest(client, "col-1", exclude_tombstoned=False)

    assert result.stats.total_rows == 1


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_all_pages_fetched():
    ds1 = _dataset(id="ds-1", assets=[_asset("s3://a")])
    ds2 = _dataset(id="ds-2", assets=[_asset("s3://b")])
    client = _client(
        _page([_dataset_entry(ds1)], total=2),
        _page([_dataset_entry(ds2)], total=2),
    )

    result = generate_manifest(client, "col-1", page_size=1)

    assert result.stats.total_rows == 2
    assert client.collections.list_entries.call_count == 2


def test_page_size_exceeding_max_warns():
    client = _client(_page([]))

    with pytest.warns(UserWarning, match="page_size=200"):
        generate_manifest(client, "col-1", page_size=200)


# ---------------------------------------------------------------------------
# Recursion
# ---------------------------------------------------------------------------


def test_child_collection_ignored_without_recurse():
    client = _client(_page([_collection_entry("col-child")]))

    result = generate_manifest(client, "col-parent")

    assert result.stats.total_rows == 0
    assert client.collections.list_entries.call_count == 1


def test_recurse_traverses_child_collection():
    child_dataset = _dataset(id="ds-child", assets=[_asset("s3://child.tiff")])
    client = _client(
        _page([_collection_entry("col-child")]),
        _page([_dataset_entry(child_dataset)]),
    )

    result = generate_manifest(client, "col-parent", recurse=True)

    assert result.stats.total_rows == 1
    assert result[0]["location_uri"] == "s3://child.tiff"
    assert client.collections.list_entries.call_count == 2


def test_recurse_cycle_detection():
    """A collection that references itself should not loop infinitely."""
    client = _client(_page([_collection_entry("col-parent")]))

    result = generate_manifest(client, "col-parent", recurse=True)

    assert result.stats.total_rows == 0
    assert client.collections.list_entries.call_count == 1


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------


def test_on_progress_called_once_per_dataset():
    entries = [
        _dataset_entry(_dataset(id="ds-1", assets=[_asset()])),
        _dataset_entry(_dataset(id="ds-2", assets=[_asset()])),
    ]
    client = _client(_page(entries))
    progress = []

    generate_manifest(client, "col-1", on_progress=progress.append)

    assert progress == [1, 2]


def test_on_progress_called_for_tombstoned_datasets():
    entries = [
        _dataset_entry(_dataset(id="ds-live", assets=[_asset()])),
        _dataset_entry(_dataset(id="ds-dead", tombstoned=True)),
    ]
    client = _client(_page(entries))
    progress = []

    generate_manifest(client, "col-1", on_progress=progress.append)

    assert len(progress) == 2


# ---------------------------------------------------------------------------
# generate_manifest_iter
# ---------------------------------------------------------------------------


def test_iter_yields_rows():
    dataset = _dataset(assets=[_asset()])
    client = _client(_page([_dataset_entry(dataset)]))

    rows = list(generate_manifest_iter(client, "col-1"))

    assert len(rows) == 1
    assert rows[0]["dataset_id"] == "ds-1"


def test_iter_is_lazy(monkeypatch):
    """Rows are yielded page-by-page, not buffered."""
    dataset = _dataset(assets=[_asset()])
    client = _client(_page([_dataset_entry(dataset)]))

    gen = generate_manifest_iter(client, "col-1")
    client.collections.list_entries.assert_not_called()

    next(gen)
    client.collections.list_entries.assert_called_once()


# ---------------------------------------------------------------------------
# ManifestResult list-like interface
# ---------------------------------------------------------------------------


def test_manifest_result_bool_false_when_empty():
    result = generate_manifest(_client(_page([])), "col-1")
    assert not result


def test_manifest_result_supports_len_iter_index():
    dataset = _dataset(assets=[_asset("s3://a"), _asset("s3://b")])
    client = _client(_page([_dataset_entry(dataset)]))

    result = generate_manifest(client, "col-1")

    assert len(result) == 2
    assert result[0]["location_uri"] == "s3://a"
    assert [r["location_uri"] for r in result] == ["s3://a", "s3://b"]
