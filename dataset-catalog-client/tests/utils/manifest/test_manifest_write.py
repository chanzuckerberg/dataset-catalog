"""Unit tests for write_manifest (CSV and JSON output)."""

import csv
import json
import os

import pytest

from catalog_client.utils.manifest import ManifestResult, ManifestStats, write_manifest

_ROWS = [
    {"dataset_id": "ds-1", "location_uri": "s3://bucket/a.tiff", "split": "train"},
    {"dataset_id": "ds-2", "location_uri": "s3://bucket/b.tiff", "split": "test"},
]


def _result(rows=None):
    return ManifestResult(
        rows=rows if rows is not None else list(_ROWS), stats=ManifestStats()
    )


def _read_rows(path, fmt):
    if fmt == "csv":
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt,ext", [("csv", ".csv"), ("json", ".json")])
def test_write_creates_file(tmp_path, fmt, ext):
    dest = tmp_path / f"manifest{ext}"
    write_manifest(_result(), dest, format=fmt)
    assert dest.exists()


@pytest.mark.parametrize("fmt,ext", [("csv", ".csv"), ("json", ".json")])
def test_write_row_count(tmp_path, fmt, ext):
    dest = tmp_path / f"manifest{ext}"
    write_manifest(_result(), dest, format=fmt)
    assert len(_read_rows(dest, fmt)) == len(_ROWS)


@pytest.mark.parametrize(
    "fmt,ext,idx,key,expected",
    [
        ("csv", ".csv", 0, "dataset_id", "ds-1"),
        ("csv", ".csv", 1, "location_uri", "s3://bucket/b.tiff"),
        ("json", ".json", 0, "dataset_id", "ds-1"),
        ("json", ".json", 1, "split", "test"),
    ],
)
def test_write_row_values(tmp_path, fmt, ext, idx, key, expected):
    dest = tmp_path / f"manifest{ext}"
    write_manifest(_result(), dest, format=fmt)
    assert _read_rows(dest, fmt)[idx][key] == expected


def test_write_csv_header_matches_row_keys(tmp_path):
    dest = tmp_path / "manifest.csv"
    write_manifest(_result(), dest)
    with dest.open(newline="", encoding="utf-8") as f:
        assert csv.DictReader(f).fieldnames == list(_ROWS[0].keys())


def test_write_json_output_is_list(tmp_path):
    dest = tmp_path / "manifest.json"
    write_manifest(_result(), dest, format="json")
    assert isinstance(json.loads(dest.read_text(encoding="utf-8")), list)


def test_write_csv_is_default_format(tmp_path):
    dest = tmp_path / "out"
    write_manifest(_result(), dest)  # no format= argument
    with dest.open(newline="", encoding="utf-8") as f:
        assert csv.DictReader(f).fieldnames is not None


def test_write_accepts_string_path(tmp_path):
    dest = str(tmp_path / "manifest.csv")
    write_manifest(_result(), dest)
    assert os.path.exists(dest)


# ---------------------------------------------------------------------------
# Input types — ManifestResult, list, generator all accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("input_type", ["result", "list", "generator"])
def test_write_accepts_various_input_types(tmp_path, input_type):
    dest = tmp_path / "out.csv"
    if input_type == "result":
        rows = _result()
    elif input_type == "list":
        rows = list(_ROWS)
    else:
        rows = iter(_ROWS)
    write_manifest(rows, dest)
    assert len(_read_rows(dest, "csv")) == len(_ROWS)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("empty_rows", [[], _result(rows=[])])
def test_write_empty_input_raises(tmp_path, empty_rows):
    with pytest.raises(ValueError, match="empty"):
        write_manifest(empty_rows, tmp_path / "out.csv")


def test_write_unsupported_format_raises():
    with pytest.raises(ValueError, match="Unsupported format"):
        write_manifest(_result(), "/dev/null", format="parquet")  # type: ignore[arg-type]
