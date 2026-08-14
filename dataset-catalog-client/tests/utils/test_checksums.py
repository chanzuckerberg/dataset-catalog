"""Tests for checksum utilities module.

These are integration-level tests: the S3 cases drive real boto3 request/response
shapes through moto, so they cover the wiring that tests/utils/checksum/test_generate.py
deliberately mocks out (metadata key casing, HeadObject response fields, error types).
"""

import hashlib

import boto3
import pytest
from moto import mock_aws

from catalog_client.models.asset import AssetType, DataAssetRequest, StoragePlatform
from catalog_client.utils import checksum as checksums
from catalog_client.utils.checksum.algorithm import DIGEST_HEX_LENGTH, Algorithm
from catalog_client.utils.checksum.models import ChecksumResult
from catalog_client.utils.checksum.s3 import (
    _fetch_all_s3_stored_checksums,
    _find_common_algorithm_in_folder,
    _parse_s3_uri,
    _select_best_algorithm,
)

BUCKET = "test-bucket"
HEX64 = "aa" * 32  # a valid blake3-length hex digest


def hex64(seed: str) -> str:
    """A distinct but well-formed 64-char (blake3-width) hex digest.

    Stored checksums must be hex of the algorithm's exact width — placeholder
    strings like "hash_b3" are rejected at read time — so tests that only need
    "some digest" derive one deterministically from a label.
    """
    return hashlib.blake2b(seed.encode(), digest_size=32).hexdigest()


def hex_for(seed: str, algorithm: Algorithm) -> str:
    """A well-formed digest of the right width for `algorithm`."""
    width = DIGEST_HEX_LENGTH[algorithm]
    return hashlib.blake2b(seed.encode(), digest_size=width // 2).hexdigest()


@pytest.fixture
def s3():
    """A moto-backed S3 client with the test bucket already created.

    The mock_aws context is held open by the fixture rather than applied as a class
    decorator, so that bucket setup and the test body share one mocked session.
    """
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def make_asset(uri, asset_type=AssetType.file, platform=StoragePlatform.s3, **kwargs):
    return DataAssetRequest(
        location_uri=uri, asset_type=asset_type, storage_platform=platform, **kwargs
    )


# ── URI Parsing ────────────────────────────────────────────────────────────────


class TestParseS3Uri:
    @pytest.mark.parametrize(
        "uri, expected_bucket, expected_key",
        [
            ("s3://my-bucket/path/to/key", "my-bucket", "path/to/key"),
            ("s3a://my-bucket/path/to/key", "my-bucket", "path/to/key"),
            ("s3://my-bucket/", "my-bucket", ""),
            ("s3://my-bucket", "my-bucket", ""),
        ],
    )
    def test_valid_uris(self, uri, expected_bucket, expected_key):
        bucket, key = _parse_s3_uri(uri)
        assert bucket == expected_bucket
        assert key == expected_key

    def test_invalid_uri_raises(self):
        with pytest.raises(ValueError, match="Not an S3 URI"):
            _parse_s3_uri("http://example.com/file")


# ── Algorithm Selection ────────────────────────────────────────────────────────


class TestSelectBestAlgorithm:
    @pytest.mark.parametrize(
        "algorithms, expected",
        [
            ({"blake3", "crc32"}, "blake3"),
            ({"crc32", "crc64nvme"}, "crc64nvme"),
            ({"crc32"}, "crc32"),
            ({"blake2b", "crc64"}, "blake2b"),
            ({"blake3", "blake2b", "crc64", "crc64nvme", "crc32"}, "blake3"),
            (set(), None),
        ],
    )
    def test_priority_selection(self, algorithms, expected):
        assert _select_best_algorithm(algorithms) == expected


# ── S3 Stored Checksum Fetching ────────────────────────────────────────────────


class TestFetchAllS3StoredChecksums:
    def test_no_metadata_checksums(self, s3):
        s3.put_object(Bucket=BUCKET, Key="plain.txt", Body=b"data")

        result = _fetch_all_s3_stored_checksums(BUCKET, "plain.txt", s3)
        for algo in ["blake3", "blake2b", "crc64"]:
            assert algo not in result

    def test_metadata_checksums_with_merkle(self, s3):
        file_hash, merkle = hex64("file"), hex64("merkle")
        s3.put_object(
            Bucket=BUCKET,
            Key="meta.txt",
            Body=b"data",
            Metadata={
                "x-checksum-blake3": file_hash,
                "x-checksum-blake3-merkle": merkle,
            },
        )

        result = _fetch_all_s3_stored_checksums(BUCKET, "meta.txt", s3)
        assert result["blake3"].file_hash == file_hash
        assert result["blake3"].merkle_root == merkle
        assert result["blake3"].source == "s3_metadata"

    def test_metadata_without_merkle_uses_file_hash(self, s3):
        digest = hex_for("crc64-value", Algorithm.crc64)
        s3.put_object(
            Bucket=BUCKET,
            Key="meta.txt",
            Body=b"data",
            Metadata={"x-checksum-crc64": digest},
        )

        result = _fetch_all_s3_stored_checksums(BUCKET, "meta.txt", s3)
        assert result["crc64"].merkle_root == digest

    def test_nonexistent_object_returns_empty(self, s3):
        assert _fetch_all_s3_stored_checksums(BUCKET, "missing.txt", s3) == {}

    def test_multiple_metadata_algorithms(self, s3):
        s3.put_object(
            Bucket=BUCKET,
            Key="multi.txt",
            Body=b"data",
            Metadata={
                "x-checksum-blake3": hex_for("b3", Algorithm.blake3),
                "x-checksum-blake2b": hex_for("b2", Algorithm.blake2b),
            },
        )

        result = _fetch_all_s3_stored_checksums(BUCKET, "multi.txt", s3)
        assert "blake3" in result
        assert "blake2b" in result

    @pytest.mark.parametrize(
        "bad_value, why",
        [
            ("not-hex-at-all", "non-hex characters"),
            ("aabb", "hex but far too short for blake3"),
            ("aa" * 64, "hex but too long for blake3"),
        ],
    )
    def test_malformed_metadata_digest_is_ignored(self, s3, bad_value, why):
        """A stored value that is not a well-formed digest is not usable.

        It could not be packed into a parent folder's Merkle root, so admitting
        it would make a file's checksum depend on whether it was hashed alone
        or as a folder child. It is dropped at read time instead.
        """
        s3.put_object(
            Bucket=BUCKET,
            Key="bad.txt",
            Body=b"data",
            Metadata={"x-checksum-blake3": bad_value},
        )

        result = _fetch_all_s3_stored_checksums(BUCKET, "bad.txt", s3)
        assert "blake3" not in result, why

    def test_one_bad_value_does_not_discard_the_others(self, s3):
        """A single unreadable checksum must not hide the object's good ones."""
        good = hex_for("b2", Algorithm.blake2b)
        s3.put_object(
            Bucket=BUCKET,
            Key="mixed.txt",
            Body=b"data",
            Metadata={
                "x-checksum-blake3": "garbage",
                "x-checksum-blake2b": good,
            },
        )

        result = _fetch_all_s3_stored_checksums(BUCKET, "mixed.txt", s3)
        assert "blake3" not in result
        assert result["blake2b"].file_hash == good

    def test_non_missing_error_is_raised_not_swallowed(self, s3):
        """An access error is a real problem, not "this object has no checksum".

        Swallowing it would silently trigger a full download, or a silent skip
        under compute_if_no_s3_checksum=False.
        """
        with pytest.raises(Exception, match="NoSuchBucket|AccessDenied|404"):
            _fetch_all_s3_stored_checksums("no-such-bucket-here", "k.txt", s3)


# ── Folder Common Algorithm Detection ──────────────────────────────────────────


class TestFindCommonAlgorithmInFolder:
    def test_common_algorithm_found(self, s3):
        for name in ["a.txt", "b.txt", "c.txt"]:
            s3.put_object(
                Bucket=BUCKET,
                Key=f"dataset/{name}",
                Body=b"data",
                Metadata={"x-checksum-blake3": hex64(name)},
            )

        algo, per_child = _find_common_algorithm_in_folder(
            f"s3://{BUCKET}/dataset/", s3
        )
        assert algo == "blake3"
        assert len(per_child) == 3

    def test_early_exit_on_missing_checksum(self, s3, monkeypatch):
        """When a child has no stored checksums, exit early with None."""
        s3.put_object(Bucket=BUCKET, Key="dataset/a.txt", Body=b"data")
        s3.put_object(Bucket=BUCKET, Key="dataset/b.txt", Body=b"data")

        def _mock_fetch(bucket, key, client):
            if key == "dataset/a.txt":
                return {
                    "blake3": ChecksumResult(
                        path=f"s3://{bucket}/{key}",
                        algorithm="blake3",
                        file_hash=HEX64,
                        merkle_root=HEX64,
                        source="s3_metadata",
                    )
                }
            return {}  # b.txt has no checksums

        monkeypatch.setattr(
            "catalog_client.utils.checksum.s3._fetch_all_s3_stored_checksums",
            _mock_fetch,
        )
        algo, per_child = _find_common_algorithm_in_folder(
            f"s3://{BUCKET}/dataset/", s3
        )
        assert algo is None
        assert per_child == {}

    def test_intersection_finds_shared_algorithm(self, s3):
        """File A has {blake3, crc64}, File B has {crc64} -> crc64 is common."""
        s3.put_object(
            Bucket=BUCKET,
            Key="dataset/a.txt",
            Body=b"data",
            Metadata={
                "x-checksum-blake3": hex_for("b3", Algorithm.blake3),
                "x-checksum-crc64": hex_for("c64-a", Algorithm.crc64),
            },
        )
        s3.put_object(
            Bucket=BUCKET,
            Key="dataset/b.txt",
            Body=b"data",
            Metadata={"x-checksum-crc64": hex_for("c64-b", Algorithm.crc64)},
        )

        algo, per_child = _find_common_algorithm_in_folder(
            f"s3://{BUCKET}/dataset/", s3
        )
        assert algo == "crc64"
        assert len(per_child) == 2

    def test_empty_folder_returns_none(self, s3):
        algo, per_child = _find_common_algorithm_in_folder(f"s3://{BUCKET}/empty/", s3)
        assert algo is None
        assert per_child == {}

    def test_local_path_returns_none(self):
        algo, per_child = _find_common_algorithm_in_folder("/local/path", None)
        assert algo is None
        assert per_child == {}


# ── for_assets: Core Behaviors ─────────────────────────────────────────────────


class TestGenerateForAssetsCore:
    def test_empty_list(self):
        assert checksums.for_assets([]) == []

    def test_skips_assets_with_existing_checksums(self):
        assets = [
            make_asset(
                "/hpc/existing.txt",
                platform=StoragePlatform.sf_hpc,
                checksum="existing123",
                checksum_alg="blake3",
            )
        ]
        result = checksums.for_assets(assets, algorithm="crc32")
        assert result[0].checksum == "existing123"
        assert result[0].checksum_alg == "blake3"

    def test_unsupported_platform_warns_and_preserves_asset(self):
        assets = [
            make_asset("http://example.com/file.txt", platform=StoragePlatform.other)
        ]
        with pytest.warns(checksums.ChecksumWarning, match="not supported") as rec:
            result = checksums.for_assets(assets, algorithm="blake3")
        assert len(rec) == 1
        assert result[0].checksum is None


# ── for_assets: Filesystem ─────────────────────────────────────────────────────


class TestGenerateForAssetsFilesystem:
    @pytest.mark.parametrize(
        "algorithm, expected_hex_len",
        [
            ("blake3", 64),
            ("blake2b", 128),
            ("crc32", 8),
        ],
    )
    def test_local_file_with_algorithm(self, tmp_path, algorithm, expected_hex_len):
        target = tmp_path / "file.txt"
        target.write_text("test content")

        assets = [make_asset(str(target), platform=StoragePlatform.sf_hpc)]
        result = checksums.for_assets(assets, algorithm=algorithm)
        assert result[0].checksum_alg == algorithm
        assert len(result[0].checksum) == expected_hex_len

    def test_local_directory(self, tmp_path):
        for name in ["a.txt", "b.txt"]:
            (tmp_path / name).write_text(f"content_{name}")

        assets = [
            make_asset(
                str(tmp_path),
                asset_type=AssetType.folder,
                platform=StoragePlatform.sf_hpc,
            )
        ]
        result = checksums.for_assets(assets, algorithm="blake3")
        assert result[0].checksum is not None
        assert result[0].checksum_alg == "blake3"

    def test_nonexistent_file_warns(self):
        assets = [make_asset("/nonexistent/file.txt", platform=StoragePlatform.sf_hpc)]
        with pytest.warns(
            checksums.ChecksumWarning, match="Failed to generate checksum"
        ) as rec:
            result = checksums.for_assets(assets, algorithm="blake3")
        assert len(rec) == 1
        assert result[0].checksum is None

    def test_none_algorithm_defaults_to_blake3(self, tmp_path):
        target = tmp_path / "file.txt"
        target.write_text("test")

        assets = [make_asset(str(target), platform=StoragePlatform.sf_hpc)]
        result = checksums.for_assets(assets, algorithm=None)
        assert result[0].checksum_alg == "blake3"


# ── for_assets: S3 Integration ─────────────────────────────────────────────────


class TestGenerateForAssetsS3:
    def test_explicit_algorithm(self, s3):
        s3.put_object(Bucket=BUCKET, Key="file.txt", Body=b"data")

        assets = [make_asset(f"s3://{BUCKET}/file.txt")]
        result = checksums.for_assets(assets, algorithm="blake3", s3_client=s3)
        assert result[0].checksum_alg == "blake3"
        assert result[0].checksum is not None

    def test_auto_detect_file_uses_stored_metadata(self, s3):
        """algorithm=None on S3 file with metadata -> uses stored checksum.

        Covers real S3 metadata key casing: S3 lowercases user metadata keys, which
        the s3.py lookup depends on.
        """
        stored = hex_for("stored", Algorithm.blake3)
        s3.put_object(
            Bucket=BUCKET,
            Key="file.txt",
            Body=b"data",
            Metadata={"x-checksum-blake3": stored},
        )

        assets = [make_asset(f"s3://{BUCKET}/file.txt")]
        result = checksums.for_assets(assets, algorithm=None, s3_client=s3)
        assert result[0].checksum == stored
        assert result[0].checksum_alg == "blake3"

    def test_auto_detect_file_falls_back_to_blake3(self, s3, monkeypatch):
        """algorithm=None on S3 file with no stored checksums -> computes blake3.

        The fetch must be stubbed: S3 (and moto) attach a native ChecksumCRC32 to
        every PutObject, so a genuinely checksum-free object cannot be created and
        auto-detection would otherwise legitimately choose crc32.
        """
        s3.put_object(Bucket=BUCKET, Key="file.txt", Body=b"data")
        monkeypatch.setattr(
            "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
            lambda *a, **k: {},
        )

        assets = [make_asset(f"s3://{BUCKET}/file.txt")]
        result = checksums.for_assets(assets, algorithm=None, s3_client=s3)
        assert result[0].checksum is not None
        assert result[0].checksum_alg == "blake3"

    def test_auto_detect_folder_common_algorithm(self, s3):
        """algorithm=None on S3 folder where all children share blake3."""
        for name, digest in [("a.txt", "aa" * 32), ("b.txt", "bb" * 32)]:
            s3.put_object(
                Bucket=BUCKET,
                Key=f"dataset/{name}",
                Body=b"data",
                Metadata={"x-checksum-blake3": digest},
            )

        assets = [make_asset(f"s3://{BUCKET}/dataset/", asset_type=AssetType.folder)]
        result = checksums.for_assets(assets, algorithm=None, s3_client=s3)
        assert result[0].checksum is not None
        assert result[0].checksum_alg == "blake3"

    def test_auto_detect_folder_no_common_falls_back_to_blake3(self, s3, monkeypatch):
        """algorithm=None on S3 folder with no common algorithm -> computes blake3.

        Stubbed for the same reason as the file case: every PutObject carries a
        native CRC32, so children always share at least one algorithm in practice.
        """
        for name in ["a.txt", "b.txt"]:
            s3.put_object(Bucket=BUCKET, Key=f"dataset/{name}", Body=b"data")
        monkeypatch.setattr(
            "catalog_client.utils.checksum.generate._find_common_algorithm_in_folder",
            lambda *a, **k: (None, {}),
        )

        assets = [make_asset(f"s3://{BUCKET}/dataset/", asset_type=AssetType.folder)]
        result = checksums.for_assets(assets, algorithm=None, s3_client=s3)
        assert result[0].checksum is not None
        assert result[0].checksum_alg == "blake3"

    def test_access_error_warns(self, s3):
        """A real botocore NoSuchBucket error is caught and surfaced as a warning."""
        assets = [make_asset("s3://nonexistent-bucket/file.txt")]
        with pytest.warns(
            checksums.ChecksumWarning, match="Failed to generate checksum"
        ) as rec:
            result = checksums.for_assets(assets, algorithm="blake3", s3_client=s3)
        assert len(rec) == 1
        assert result[0].checksum is None

    def test_compute_if_no_s3_checksum_false_skips_s3(self, s3):
        """S3 file with no stored checksum + flag=False -> skipped."""
        s3.put_object(Bucket=BUCKET, Key="file.txt", Body=b"data")

        assets = [make_asset(f"s3://{BUCKET}/file.txt")]
        result = checksums.for_assets(
            assets, algorithm="blake3", compute_if_no_s3_checksum=False, s3_client=s3
        )
        assert result[0].checksum is None

    def test_compute_if_no_s3_checksum_false_does_not_skip_local(self, tmp_path):
        """Non-S3 asset is still computed even with flag=False."""
        target = tmp_path / "file.txt"
        target.write_text("data")

        assets = [make_asset(str(target), platform=StoragePlatform.sf_hpc)]
        result = checksums.for_assets(
            assets, algorithm="blake3", compute_if_no_s3_checksum=False
        )
        assert result[0].checksum is not None

    def test_mixed_platforms(self, s3, tmp_path):
        """S3, local, and unsupported assets processed correctly together."""
        s3.put_object(Bucket=BUCKET, Key="test.txt", Body=b"s3 content")
        local = tmp_path / "local.txt"
        local.write_text("local content")

        assets = [
            make_asset(f"s3://{BUCKET}/test.txt"),
            make_asset(str(local), platform=StoragePlatform.sf_hpc),
            make_asset("http://unsupported.com/file", platform=StoragePlatform.other),
        ]

        with pytest.warns(checksums.ChecksumWarning, match="not supported"):
            result = checksums.for_assets(assets, algorithm="blake3", s3_client=s3)

        assert result[0].checksum is not None  # S3
        assert result[1].checksum is not None  # local
        assert result[2].checksum is None  # unsupported
