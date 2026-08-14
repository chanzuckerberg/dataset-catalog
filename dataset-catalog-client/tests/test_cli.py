import json
import re

import boto3
import pytest
from moto import mock_aws
from pytest_httpx import HTTPXMock

from catalog_client.cli import main
from catalog_client.utils.checksum import Algorithm
from catalog_client.utils.checksum.hashing import compute_checksum_localfs

BASE = "http://test.local"
TOKEN = "tok"

DATASET_RESPONSE = {
    "id": "uuid-1",
    "tombstoned": False,
    "created_at": "2024-01-01T00:00:00Z",
    "created_by": "user-1",
    "last_modified_at": "2024-01-01T00:00:00Z",
    "modified_by": None,
    "canonical_id": "ds-001",
    "version": "1.0.0",
    "project": "atlas",
    "locations": [],
    "name": "Test",
    "modality": "sequencing",
    "dataset_type": "raw",
    "governance": {},
    "data_quality": None,
    "metadata": {},
    "record_version": 1,
    "description": None,
    "doi": None,
    "cross_db_references": None,
    "is_latest": True,
    "record_schema_version": None,
    "metadata_schema": None,
}

SEARCH_HIT = {
    "id": "uuid-1",
    "canonical_id": "ds-001",
    "version": "1.0.0",
    "name": "Test",
    "modality": "sequencing",
    "dataset_type": "raw",
    "project": "atlas",
    "is_latest": True,
}

SEARCH_RESPONSE = {
    "total": 1,
    "limit": 10,
    "offset": 0,
    "results": [SEARCH_HIT],
    "facets": {"organism": [{"value": "Homo sapiens", "count": 1}]},
}

LINEAGE_EDGE = {
    "id": "edge-1",
    "source_dataset_id": "uuid-parent",
    "destination_dataset_id": "uuid-1",
    "lineage_type": "transformed_from",
    "source_data_asset_id": None,
    "destination_data_asset_id": None,
    "metadata": None,
    "tombstoned": False,
    "created_at": "2024-01-01T00:00:00Z",
    "last_modified_at": "2024-01-01T00:00:00Z",
}

EMPTY_PAGE = {"total": 0, "limit": 100, "offset": 0, "results": []}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CATALOG_API_URL", BASE)
    monkeypatch.setenv("CATALOG_API_TOKEN", TOKEN)


def _output(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_missing_env_exits_usage(monkeypatch):
    monkeypatch.delenv("CATALOG_API_TOKEN")
    with pytest.raises(SystemExit) as exc:
        main(["search", "--q", "x"])
    assert exc.value.code == 2


def test_auth_error_exit_code(httpx_mock: HTTPXMock, capsys):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/search/\?.*"),
        status_code=401,
        json={"detail": "invalid token"},
    )
    with pytest.raises(SystemExit) as exc:
        main(["search", "--q", "x"])
    assert exc.value.code == 3
    assert "authentication failed" in capsys.readouterr().err


def test_not_found_exit_code(httpx_mock: HTTPXMock, capsys):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/missing.*"),
        status_code=404,
        json={"detail": "no such dataset"},
    )
    with pytest.raises(SystemExit) as exc:
        main(["get", "missing"])
    assert exc.value.code == 4
    err = capsys.readouterr().err
    assert err.startswith("error: not found")


def test_server_error_exit_code(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/search/\?.*"),
        status_code=503,
        json={"detail": "down"},
    )
    with pytest.raises(SystemExit) as exc:
        main(["search", "--q", "x"])
    assert exc.value.code == 5


def test_table_output_when_forced(httpx_mock: HTTPXMock, capsys):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/search/\?.*"),
        json=SEARCH_RESPONSE,
    )
    main(["search", "--q", "brightfield", "-o", "table"])
    out = capsys.readouterr().out
    # Header + separator + one data row, not JSON.
    assert "CANONICAL_ID" in out
    assert "ds-001" in out
    assert not out.lstrip().startswith("{")


def test_table_is_default_on_tty(httpx_mock: HTTPXMock, capsys, monkeypatch):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/search/\?.*"),
        json=SEARCH_RESPONSE,
    )
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    main(["search", "--q", "brightfield"])
    assert "CANONICAL_ID" in capsys.readouterr().out


def test_facets_table_output(httpx_mock: HTTPXMock, capsys):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/search/\?.*"),
        json=SEARCH_RESPONSE,
    )
    main(["facets", "--fields", "organism", "-o", "table"])
    out = capsys.readouterr().out
    assert "VALUE" in out and "COUNT" in out
    assert "Homo sapiens" in out


def test_search(httpx_mock: HTTPXMock, capsys):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/search/\?.*"),
        json=SEARCH_RESPONSE,
    )
    main(["search", "--q", "brightfield", "--facets", "organism"])
    out = _output(capsys)
    assert out["total"] == 1
    assert out["results"][0]["canonical_id"] == "ds-001"
    assert out["facets"]["organism"][0]["value"] == "Homo sapiens"
    request = httpx_mock.get_request()
    assert request.url.params["q"] == "brightfield"
    assert request.url.params["sort"] == "relevance"
    assert request.url.params["is_latest"] == "true"


def test_search_defaults_to_last_modified_without_q(httpx_mock: HTTPXMock, capsys):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/search/\?.*"),
        json=SEARCH_RESPONSE,
    )
    main(["search", "--organism", "Homo sapiens", "--all-versions"])
    request = httpx_mock.get_request()
    assert request.url.params["sort"] == "last_modified"
    assert request.url.params["organism"] == "Homo sapiens"
    assert "is_latest" not in request.url.params


def test_search_rejects_bad_modality():
    with pytest.raises(SystemExit):
        main(["search", "--modality", "bogus"])


def test_facets(httpx_mock: HTTPXMock, capsys):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/search/\?.*"),
        json=SEARCH_RESPONSE,
    )
    main(["facets", "--fields", "organism"])
    out = _output(capsys)
    assert out == {
        "total": 1,
        "facets": {"organism": [{"value": "Homo sapiens", "count": 1}]},
    }


def test_get_by_id(httpx_mock: HTTPXMock, capsys):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/uuid-1.*"),
        json=DATASET_RESPONSE,
    )
    main(["get", "uuid-1"])
    assert _output(capsys)["id"] == "uuid-1"


def test_get_by_coordinates(httpx_mock: HTTPXMock, capsys):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/\?.*"),
        json={"total": 1, "limit": 10, "offset": 0, "results": [DATASET_RESPONSE]},
    )
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/uuid-1.*"),
        json=DATASET_RESPONSE,
    )
    main(["get", "ds-001", "--version", "1.0.0", "--project", "atlas"])
    assert _output(capsys)["canonical_id"] == "ds-001"


def test_get_coordinates_require_both_parts():
    with pytest.raises(SystemExit):
        main(["get", "ds-001", "--version", "1.0.0"])


def test_list_summarizes_by_default(httpx_mock: HTTPXMock, capsys):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/\?.*"),
        json={"total": 1, "limit": 100, "offset": 0, "results": [DATASET_RESPONSE]},
    )
    main(["list", "--project", "atlas"])
    out = _output(capsys)
    assert out["results"][0] == {
        "id": "uuid-1",
        "canonical_id": "ds-001",
        "version": "1.0.0",
        "name": "Test",
        "project": "atlas",
        "modality": "sequencing",
        "dataset_type": "raw",
        "is_latest": True,
        "last_modified_at": "2024-01-01 00:00:00+00:00",
    }


def test_lineage_walk_up(httpx_mock: HTTPXMock, capsys):
    # Hop 1: uuid-1 has one incoming edge from uuid-parent.
    httpx_mock.add_response(
        url=re.compile(
            rf"{re.escape(BASE)}/api/lineage/\?.*destination_dataset_id=uuid-1.*"
        ),
        json={"total": 1, "limit": 100, "offset": 0, "results": [LINEAGE_EDGE]},
    )
    # Hop 2: uuid-parent has no further ancestors.
    httpx_mock.add_response(
        url=re.compile(
            rf"{re.escape(BASE)}/api/lineage/\?.*destination_dataset_id=uuid-parent.*"
        ),
        json=EMPTY_PAGE,
    )
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/uuid-1.*"),
        json=DATASET_RESPONSE,
    )
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/datasets/uuid-parent.*"),
        json={**DATASET_RESPONSE, "id": "uuid-parent", "canonical_id": "ds-000"},
    )
    main(["lineage", "uuid-1", "--direction", "up"])
    out = _output(capsys)
    assert set(out["datasets"]) == {"uuid-1", "uuid-parent"}
    assert out["edges"] == [{key: value for key, value in LINEAGE_EDGE.items()}]


def test_collections_entries(httpx_mock: HTTPXMock, capsys):
    httpx_mock.add_response(
        url=re.compile(rf"{re.escape(BASE)}/api/collections/col-1/entries\?.*"),
        json={
            "total": 1,
            "limit": 100,
            "offset": 0,
            "results": [{"entry_type": "dataset", "entry": DATASET_RESPONSE}],
        },
    )
    main(["collections", "entries", "col-1"])
    out = _output(capsys)
    assert out["results"][0]["entry_type"] == "dataset"
    assert out["results"][0]["entry"]["canonical_id"] == "ds-001"


def test_collections_get_requires_id():
    with pytest.raises(SystemExit):
        main(["collections", "get"])


# ── checksum ───────────────────────────────────────────────────────────────────


@pytest.fixture
def aws_env(monkeypatch):
    """Credentials/region for the boto3 client the checksum command builds itself."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


def test_checksum_local_file_matches_library(tmp_path, capsys):
    target = tmp_path / "data.bin"
    target.write_bytes(b"x" * 5000)
    expected = compute_checksum_localfs(str(target), Algorithm.blake2b)

    main(["checksum", str(target), "--algorithm", "blake2b"])

    out = _output(capsys)
    assert out["content_digest"] == expected.content_digest
    assert out["algorithm"] == "blake2b"
    assert out["total_size"] == 5000
    assert out["source"] == "computed"
    assert out["is_directory"] is False
    assert out["s3_base64"]
    assert out["s3_composite_base64"]


def test_checksum_table_is_default_on_tty(tmp_path, capsys, monkeypatch):
    target = tmp_path / "data.bin"
    target.write_bytes(b"hello")
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    main(["checksum", str(target), "--algorithm", "crc32"])

    out = capsys.readouterr().out
    assert "DIGEST" in out and "SOURCE" in out
    # 8 hex chars for crc32, printed in full rather than truncated
    assert compute_checksum_localfs(str(target), Algorithm.crc32).file_hash in out


def test_checksum_directory_children(tmp_path, capsys):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_bytes(b"a")
    (tmp_path / "sub" / "b.txt").write_bytes(b"b")

    main(
        ["checksum", str(tmp_path), "--algorithm", "crc32", "-o", "table", "--children"]
    )

    out = capsys.readouterr().out
    assert "folder" in out
    assert "a.txt" in out and "b.txt" in out


def test_checksum_directory_json_omits_composite(tmp_path, capsys):
    (tmp_path / "a.txt").write_bytes(b"a")

    main(["checksum", str(tmp_path), "--algorithm", "crc32"])

    out = _output(capsys)
    assert out["is_directory"] is True
    # A directory Merkle root is not an S3 multipart composite checksum.
    assert "s3_composite_base64" not in out
    assert "a.txt" in out["children"]


def test_checksum_missing_path_exits_not_found(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["checksum", "/definitely/not/here"])
    assert exc.value.code == 4
    assert "error:" in capsys.readouterr().err


def test_checksum_unknown_algorithm_exits_usage(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["checksum", str(tmp_path), "--algorithm", "md5"])
    assert exc.value.code == 2


def test_checksum_needs_no_catalog_credentials(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("CATALOG_API_URL")
    monkeypatch.delenv("CATALOG_API_TOKEN")
    target = tmp_path / "data.bin"
    target.write_bytes(b"z")

    main(["checksum", str(target), "--algorithm", "crc32"])

    assert _output(capsys)["content_digest"]


def test_checksum_s3_reuses_stored_checksum(aws_env, capsys):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="cli-bucket")
        s3.put_object(Bucket="cli-bucket", Key="obj.bin", Body=b"payload")

        # No --algorithm: the algorithm is detected from what S3 already stores
        # (moto attaches a native CRC32), so the object is not downloaded.
        main(["checksum", "s3://cli-bucket/obj.bin"])
        stored = _output(capsys)

        main(
            [
                "checksum",
                "s3://cli-bucket/obj.bin",
                "--algorithm",
                "crc32",
                "--recompute",
            ]
        )
        recomputed = _output(capsys)

    assert stored["algorithm"] == "crc32"
    assert stored["source"] == "s3_native"
    assert recomputed["source"] == "computed"
    # Same content, same digest, whichever way it was obtained.
    assert stored["content_digest"] == recomputed["content_digest"]
    assert stored["total_size"] == recomputed["total_size"] == 7


def test_checksum_s3_missing_object_exits_not_found(aws_env, capsys):
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="cli-bucket")
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "checksum",
                    "s3://cli-bucket/absent.bin",
                    "--algorithm",
                    "crc32",
                    "--recompute",
                ]
            )
    assert exc.value.code == 4
    assert "error:" in capsys.readouterr().err


def test_checksum_bad_s3_uri_exits_usage(aws_env, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["checksum", "s3://", "--algorithm", "crc32"])
    assert exc.value.code == 2
