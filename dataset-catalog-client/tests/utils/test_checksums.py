"""Tests for checksum utilities module."""

import os
import tempfile
import warnings
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from catalog_client.models.asset import AssetType, DataAssetRequest, StoragePlatform
from catalog_client.utils import checksums
from catalog_client.utils.checksum.models import ChecksumResult
from catalog_client.utils.checksum_generator import (
    _fetch_all_s3_stored_checksums,
    _find_common_algorithm_in_folder,
    _parse_s3_uri,
    _select_best_algorithm,
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


# ── Platform Detection ─────────────────────────────────────────────────────────


class TestPlatformDetection:
    @pytest.mark.parametrize(
        "uri, expected",
        [
            ("s3://bucket/key", StoragePlatform.s3),
            ("s3a://bucket/key", StoragePlatform.s3),
            ("/hpc/data/file.txt", StoragePlatform.hpc),
            ("/bruno_hpc/data/file.txt", StoragePlatform.bruno_hpc),
            ("/coreweave/data/file.txt", StoragePlatform.coreweave),
            ("http://example.com/file.txt", None),
        ],
    )
    def test_detect_platform_from_uri(self, uri, expected):
        assert checksums._detect_platform(uri) == expected

    def test_explicit_platform_overrides_uri(self):
        asset = DataAssetRequest(
            location_uri="file:///local/path",
            asset_type=AssetType.file,
            storage_platform=StoragePlatform.s3,
        )
        assert checksums._determine_platform(asset) == StoragePlatform.s3

    @pytest.mark.parametrize(
        "platform", [StoragePlatform.external, StoragePlatform.other]
    )
    def test_unsupported_explicit_platform_returns_none(self, platform):
        asset = DataAssetRequest(
            location_uri="s3://bucket/key",
            asset_type=AssetType.file,
            storage_platform=platform,
        )
        assert checksums._determine_platform(asset) is None


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


@mock_aws
class TestFetchAllS3StoredChecksums:
    def _setup_bucket(self):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        return s3

    def test_no_metadata_checksums(self):
        s3 = self._setup_bucket()
        s3.put_object(Bucket="test-bucket", Key="plain.txt", Body=b"data")

        result = _fetch_all_s3_stored_checksums("test-bucket", "plain.txt", s3)
        for algo in ["blake3", "blake2b", "crc64"]:
            assert algo not in result

    def test_metadata_checksums_with_merkle(self):
        s3 = self._setup_bucket()
        s3.put_object(
            Bucket="test-bucket",
            Key="meta.txt",
            Body=b"data",
            Metadata={
                "x-checksum-blake3": "abc123",
                "x-checksum-blake3-merkle": "def456",
            },
        )

        result = _fetch_all_s3_stored_checksums("test-bucket", "meta.txt", s3)
        assert result["blake3"].file_hash == "abc123"
        assert result["blake3"].merkle_root == "def456"
        assert result["blake3"].source == "s3_metadata"

    def test_metadata_without_merkle_uses_file_hash(self):
        s3 = self._setup_bucket()
        s3.put_object(
            Bucket="test-bucket",
            Key="meta.txt",
            Body=b"data",
            Metadata={"x-checksum-crc64": "aabbccdd"},
        )

        result = _fetch_all_s3_stored_checksums("test-bucket", "meta.txt", s3)
        assert result["crc64"].merkle_root == "aabbccdd"

    def test_nonexistent_object_returns_empty(self):
        s3 = self._setup_bucket()
        assert _fetch_all_s3_stored_checksums("test-bucket", "missing.txt", s3) == {}

    def test_multiple_metadata_algorithms(self):
        s3 = self._setup_bucket()
        s3.put_object(
            Bucket="test-bucket",
            Key="multi.txt",
            Body=b"data",
            Metadata={
                "x-checksum-blake3": "hash_b3",
                "x-checksum-blake2b": "hash_b2",
            },
        )

        result = _fetch_all_s3_stored_checksums("test-bucket", "multi.txt", s3)
        assert "blake3" in result
        assert "blake2b" in result


# ── Folder Common Algorithm Detection ──────────────────────────────────────────


@mock_aws
class TestFindCommonAlgorithmInFolder:
    def _setup_bucket(self):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        return s3

    def test_common_algorithm_found(self):
        s3 = self._setup_bucket()
        for name in ["a.txt", "b.txt", "c.txt"]:
            s3.put_object(
                Bucket="test-bucket",
                Key=f"dataset/{name}",
                Body=b"data",
                Metadata={"x-checksum-blake3": f"hash_{name}"},
            )

        algo, per_child = _find_common_algorithm_in_folder(
            "s3://test-bucket/dataset/", s3
        )
        assert algo == "blake3"
        assert len(per_child) == 3

    def test_early_exit_on_missing_checksum(self):
        """When a child has no stored checksums, exit early with None."""
        s3 = self._setup_bucket()
        s3.put_object(Bucket="test-bucket", Key="dataset/a.txt", Body=b"data")
        s3.put_object(Bucket="test-bucket", Key="dataset/b.txt", Body=b"data")

        def _mock_fetch(bucket, key, client):
            if key == "dataset/a.txt":
                return {
                    "blake3": ChecksumResult(
                        path=f"s3://{bucket}/{key}",
                        algorithm="blake3",
                        file_hash="aa" * 32,
                        merkle_root="aa" * 32,
                        source="s3_metadata",
                    )
                }
            return {}  # b.txt has no checksums

        with patch(
            "catalog_client.utils.checksum_generator._fetch_all_s3_stored_checksums",
            side_effect=_mock_fetch,
        ):
            algo, per_child = _find_common_algorithm_in_folder(
                "s3://test-bucket/dataset/", s3
            )
        assert algo is None
        assert per_child == {}

    def test_intersection_finds_shared_algorithm(self):
        """File A has {blake3, crc64}, File B has {crc64} -> crc64 is common."""
        s3 = self._setup_bucket()
        s3.put_object(
            Bucket="test-bucket",
            Key="dataset/a.txt",
            Body=b"data",
            Metadata={
                "x-checksum-blake3": "hash_b3",
                "x-checksum-crc64": "hash_c64",
            },
        )
        s3.put_object(
            Bucket="test-bucket",
            Key="dataset/b.txt",
            Body=b"data",
            Metadata={"x-checksum-crc64": "hash_c64_b"},
        )

        algo, per_child = _find_common_algorithm_in_folder(
            "s3://test-bucket/dataset/", s3
        )
        assert algo == "crc64"
        assert len(per_child) == 2

    def test_empty_folder_returns_none(self):
        s3 = self._setup_bucket()
        algo, per_child = _find_common_algorithm_in_folder(
            "s3://test-bucket/empty/", s3
        )
        assert algo is None
        assert per_child == {}

    def test_local_path_returns_none(self):
        algo, per_child = _find_common_algorithm_in_folder("/local/path", None)
        assert algo is None
        assert per_child == {}


# ── generate_for_assets: Core Behaviors ────────────────────────────────────────


class TestGenerateForAssetsCore:
    def test_empty_list(self):
        assert checksums.generate_for_assets([]) == []

    def test_skips_assets_with_existing_checksums(self):
        assets = [
            DataAssetRequest(
                location_uri="/hpc/existing.txt",
                asset_type=AssetType.file,
                storage_platform=StoragePlatform.hpc,
                checksum="existing123",
                checksum_alg="blake3",
            )
        ]
        result = checksums.generate_for_assets(assets, algorithm="crc32")
        assert result[0].checksum == "existing123"
        assert result[0].checksum_alg == "blake3"

    def test_unsupported_platform_warns_and_preserves_asset(self):
        assets = [
            DataAssetRequest(
                location_uri="http://example.com/file.txt",
                asset_type=AssetType.file,
            )
        ]
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = checksums.generate_for_assets(assets, algorithm="blake3")

            assert len(w) == 1
            assert issubclass(w[0].category, checksums.ChecksumWarning)
            assert "not supported" in str(w[0].message)
            assert result[0].checksum is None

    def test_does_not_mutate_original_assets(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("data")
            temp_path = f.name
        try:
            original = DataAssetRequest(
                location_uri=temp_path,
                asset_type=AssetType.file,
                storage_platform=StoragePlatform.hpc,
            )
            result = checksums.generate_for_assets([original], algorithm="blake3")
            assert result[0].checksum is not None
            assert original.checksum is None
        finally:
            os.unlink(temp_path)


# ── generate_for_assets: Filesystem ────────────────────────────────────────────


class TestGenerateForAssetsFilesystem:
    @pytest.mark.parametrize(
        "algorithm, expected_hex_len",
        [
            ("blake3", 64),
            ("blake2b", 128),
            ("crc32", 8),
        ],
    )
    def test_local_file_with_algorithm(self, algorithm, expected_hex_len):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test content")
            temp_path = f.name
        try:
            assets = [
                DataAssetRequest(
                    location_uri=temp_path,
                    asset_type=AssetType.file,
                    storage_platform=StoragePlatform.hpc,
                )
            ]
            result = checksums.generate_for_assets(assets, algorithm=algorithm)
            assert result[0].checksum_alg == algorithm
            assert len(result[0].checksum) == expected_hex_len
        finally:
            os.unlink(temp_path)

    def test_local_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for name in ["a.txt", "b.txt"]:
                with open(os.path.join(temp_dir, name), "w") as f:
                    f.write(f"content_{name}")

            assets = [
                DataAssetRequest(
                    location_uri=temp_dir,
                    asset_type=AssetType.folder,
                    storage_platform=StoragePlatform.hpc,
                )
            ]
            result = checksums.generate_for_assets(assets, algorithm="blake3")
            assert result[0].checksum is not None
            assert result[0].checksum_alg == "blake3"

    def test_nonexistent_file_warns(self):
        assets = [
            DataAssetRequest(
                location_uri="/nonexistent/file.txt",
                asset_type=AssetType.file,
                storage_platform=StoragePlatform.hpc,
            )
        ]
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = checksums.generate_for_assets(assets, algorithm="blake3")
            assert len(w) == 1
            assert "Failed to generate checksum" in str(w[0].message)
            assert result[0].checksum is None

    def test_none_algorithm_defaults_to_blake3(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test")
            temp_path = f.name
        try:
            assets = [
                DataAssetRequest(
                    location_uri=temp_path,
                    asset_type=AssetType.file,
                    storage_platform=StoragePlatform.hpc,
                )
            ]
            result = checksums.generate_for_assets(assets, algorithm=None)
            assert result[0].checksum_alg == "blake3"
        finally:
            os.unlink(temp_path)


# ── generate_for_assets: S3 Integration ────────────────────────────────────────


@mock_aws
class TestGenerateForAssetsS3:
    def _setup_bucket(self):
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        return s3

    def test_explicit_algorithm(self):
        s3 = self._setup_bucket()
        s3.put_object(Bucket="test-bucket", Key="file.txt", Body=b"data")

        assets = [
            DataAssetRequest(
                location_uri="s3://test-bucket/file.txt",
                asset_type=AssetType.file,
            )
        ]
        result = checksums.generate_for_assets(assets, algorithm="blake3")
        assert result[0].checksum_alg == "blake3"
        assert result[0].checksum is not None

    def test_auto_detect_file_uses_stored_metadata(self):
        """algorithm=None on S3 file with metadata -> uses stored checksum."""
        s3 = self._setup_bucket()
        s3.put_object(
            Bucket="test-bucket",
            Key="file.txt",
            Body=b"data",
            Metadata={"x-checksum-blake3": "stored_hash_value"},
        )

        assets = [
            DataAssetRequest(
                location_uri="s3://test-bucket/file.txt",
                asset_type=AssetType.file,
            )
        ]
        result = checksums.generate_for_assets(assets, algorithm=None)
        assert result[0].checksum == "stored_hash_value"
        assert result[0].checksum_alg == "blake3"

    def test_auto_detect_file_falls_back_to_blake3(self):
        """algorithm=None on S3 file with no stored checksums -> computes blake3."""
        s3 = self._setup_bucket()
        s3.put_object(Bucket="test-bucket", Key="file.txt", Body=b"data")

        assets = [
            DataAssetRequest(
                location_uri="s3://test-bucket/file.txt",
                asset_type=AssetType.file,
            )
        ]
        with patch(
            "catalog_client.utils.checksums._fetch_all_s3_stored_checksums",
            return_value={},
        ):
            result = checksums.generate_for_assets(assets, algorithm=None)
        assert result[0].checksum is not None
        assert result[0].checksum_alg == "blake3"

    def test_auto_detect_folder_common_algorithm(self):
        """algorithm=None on S3 folder where all children share blake3."""
        s3 = self._setup_bucket()
        # Use valid 64-char hex strings (blake3 digest length)
        s3.put_object(
            Bucket="test-bucket",
            Key="dataset/a.txt",
            Body=b"data",
            Metadata={"x-checksum-blake3": "aa" * 32},
        )
        s3.put_object(
            Bucket="test-bucket",
            Key="dataset/b.txt",
            Body=b"data",
            Metadata={"x-checksum-blake3": "bb" * 32},
        )

        assets = [
            DataAssetRequest(
                location_uri="s3://test-bucket/dataset/",
                asset_type=AssetType.folder,
            )
        ]
        result = checksums.generate_for_assets(assets, algorithm=None)
        assert result[0].checksum is not None
        assert result[0].checksum_alg == "blake3"

    def test_auto_detect_folder_no_common_falls_back_to_blake3(self):
        """algorithm=None on S3 folder with no common algorithm -> computes blake3."""
        s3 = self._setup_bucket()
        for name in ["a.txt", "b.txt"]:
            s3.put_object(
                Bucket="test-bucket",
                Key=f"dataset/{name}",
                Body=b"data",
            )

        assets = [
            DataAssetRequest(
                location_uri="s3://test-bucket/dataset/",
                asset_type=AssetType.folder,
            )
        ]
        with patch(
            "catalog_client.utils.checksums._find_common_algorithm_in_folder",
            return_value=(None, {}),
        ):
            result = checksums.generate_for_assets(assets, algorithm=None)
        assert result[0].checksum is not None
        assert result[0].checksum_alg == "blake3"

    def test_access_error_warns(self):
        assets = [
            DataAssetRequest(
                location_uri="s3://nonexistent-bucket/file.txt",
                asset_type=AssetType.file,
            )
        ]
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = checksums.generate_for_assets(assets, algorithm="blake3")
            assert len(w) == 1
            assert "Failed to generate checksum" in str(w[0].message)
            assert result[0].checksum is None

    def test_compute_if_no_s3_checksum_false_skips_s3(self):
        """S3 file with no stored checksum + flag=False -> skipped."""
        s3 = self._setup_bucket()
        s3.put_object(Bucket="test-bucket", Key="file.txt", Body=b"data")

        assets = [
            DataAssetRequest(
                location_uri="s3://test-bucket/file.txt",
                asset_type=AssetType.file,
            )
        ]
        result = checksums.generate_for_assets(
            assets, algorithm="blake3", compute_if_no_s3_checksum=False
        )
        assert result[0].checksum is None

    def test_compute_if_no_s3_checksum_false_does_not_skip_local(self):
        """Non-S3 asset is still computed even with flag=False."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("data")
            temp_path = f.name
        try:
            assets = [
                DataAssetRequest(
                    location_uri=temp_path,
                    asset_type=AssetType.file,
                    storage_platform=StoragePlatform.hpc,
                )
            ]
            result = checksums.generate_for_assets(
                assets, algorithm="blake3", compute_if_no_s3_checksum=False
            )
            assert result[0].checksum is not None
        finally:
            os.unlink(temp_path)

    def test_mixed_platforms(self):
        """S3, local, and unsupported assets processed correctly together."""
        s3 = self._setup_bucket()
        s3.put_object(Bucket="test-bucket", Key="test.txt", Body=b"s3 content")

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("local content")
            temp_path = f.name

        try:
            assets = [
                DataAssetRequest(
                    location_uri="s3://test-bucket/test.txt",
                    asset_type=AssetType.file,
                ),
                DataAssetRequest(
                    location_uri=temp_path,
                    asset_type=AssetType.file,
                    storage_platform=StoragePlatform.hpc,
                ),
                DataAssetRequest(
                    location_uri="http://unsupported.com/file",
                    asset_type=AssetType.file,
                ),
            ]

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = checksums.generate_for_assets(assets, algorithm="blake3")

                assert result[0].checksum is not None  # S3
                assert result[1].checksum is not None  # local
                assert result[2].checksum is None  # unsupported
                assert any("not supported" in str(x.message) for x in w)
        finally:
            os.unlink(temp_path)
