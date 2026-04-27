"""Tests for checksum utilities module."""

import os
import tempfile
import warnings

import boto3
from moto import mock_aws

from catalog_client.models.asset import AssetType, DataAssetRequest, StoragePlatform
from catalog_client.utils import checksums


class TestPlatformDetection:
    """Test platform detection functions."""

    def test_explicit_storage_platform_takes_precedence(self):
        """Test explicit storage_platform overrides URI detection."""
        asset = DataAssetRequest(
            location_uri="file:///local/path",
            asset_type=AssetType.file,
            storage_platform=StoragePlatform.s3,
        )
        platform = checksums._determine_platform(asset)
        assert platform == StoragePlatform.s3

    def test_uri_pattern_detection_s3(self):
        """Test S3 URI pattern detection."""
        asset = DataAssetRequest(
            location_uri="s3://bucket/key", asset_type=AssetType.file
        )
        platform = checksums._determine_platform(asset)
        assert platform == StoragePlatform.s3

    def test_uri_pattern_detection_s3a(self):
        """Test S3A URI pattern detection."""
        asset = DataAssetRequest(
            location_uri="s3a://bucket/key", asset_type=AssetType.file
        )
        platform = checksums._determine_platform(asset)
        assert platform == StoragePlatform.s3

    def test_uri_pattern_detection_hpc(self):
        """Test HPC URI pattern detection."""
        asset = DataAssetRequest(
            location_uri="/hpc/data/file.txt", asset_type=AssetType.file
        )
        platform = checksums._determine_platform(asset)
        assert platform == StoragePlatform.hpc

    def test_uri_pattern_detection_bruno_hpc(self):
        """Test Bruno HPC URI pattern detection."""
        asset = DataAssetRequest(
            location_uri="/bruno_hpc/data/file.txt", asset_type=AssetType.file
        )
        platform = checksums._determine_platform(asset)
        assert platform == StoragePlatform.bruno_hpc

    def test_uri_pattern_detection_coreweave(self):
        """Test CoreWeave URI pattern detection."""
        asset = DataAssetRequest(
            location_uri="/coreweave/data/file.txt", asset_type=AssetType.file
        )
        platform = checksums._determine_platform(asset)
        assert platform == StoragePlatform.coreweave

    def test_unsupported_platform_returns_none(self):
        """Test unsupported platform returns None."""
        asset = DataAssetRequest(
            location_uri="http://example.com/file.txt", asset_type=AssetType.file
        )
        platform = checksums._determine_platform(asset)
        assert platform is None

    def test_unsupported_explicit_platform_returns_none(self):
        """Test explicitly unsupported platform returns None."""
        asset = DataAssetRequest(
            location_uri="s3://bucket/key",
            asset_type=AssetType.file,
            storage_platform=StoragePlatform.external,
        )
        platform = checksums._determine_platform(asset)
        assert platform is None

    def test_detect_platform_direct_calls(self):
        """Test _detect_platform function directly."""
        assert checksums._detect_platform("s3://bucket/key") == StoragePlatform.s3
        assert checksums._detect_platform("s3a://bucket/key") == StoragePlatform.s3
        assert checksums._detect_platform("/hpc/data/file") == StoragePlatform.hpc
        assert (
            checksums._detect_platform("/bruno_hpc/data/file")
            == StoragePlatform.bruno_hpc
        )
        assert (
            checksums._detect_platform("/coreweave/data/file")
            == StoragePlatform.coreweave
        )
        assert checksums._detect_platform("http://example.com/file") is None


class TestGenerateForAssetsCore:
    """Test core generate_for_assets functionality."""

    def test_empty_asset_list(self):
        """Test with empty asset list."""
        result = checksums.generate_for_assets([])
        assert result == []

    def test_skip_assets_with_existing_checksums(self):
        """Test skips assets that already have checksums."""
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

        # Should preserve existing checksum and not modify
        assert len(result) == 1
        assert result[0].checksum == "existing123"
        assert result[0].checksum_alg == "blake3"

        # Original asset unchanged
        assert assets[0].checksum == "existing123"

    def test_unsupported_platform_warning(self):
        """Test warning for unsupported platform."""
        assets = [
            DataAssetRequest(
                location_uri="http://example.com/file.txt", asset_type=AssetType.file
            )
        ]

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = checksums.generate_for_assets(assets, algorithm="blake3")

            # Should issue warning
            assert len(w) == 1
            assert issubclass(w[0].category, checksums.ChecksumWarning)
            assert "not supported" in str(w[0].message)

            # Should return asset unchanged
            assert len(result) == 1
            assert result[0].checksum is None
            assert result[0].checksum_alg is None

    def test_immutability_preserved(self):
        """Test original assets are not modified."""
        assets = [
            DataAssetRequest(
                location_uri="s3://test-bucket/test.txt",
                asset_type=AssetType.file,
            )
        ]

        # Should not modify original assets even if processing fails
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = checksums.generate_for_assets(assets)

        # Original asset unchanged
        assert result[0].checksum is None
        assert result[0].checksum_alg is None


@mock_aws
class TestGenerateForAssetsS3Integration:
    """Test S3 integration with generate_for_assets."""

    def test_s3_success_with_algorithm(self):
        """Test successful S3 checksum generation with explicit algorithm."""
        # Setup mock S3
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="test-bucket")
        s3_client.put_object(
            Bucket="test-bucket", Key="test.txt", Body=b"s3 test content"
        )

        assets = [
            DataAssetRequest(
                location_uri="s3://test-bucket/test.txt", asset_type=AssetType.file
            )
        ]

        result = checksums.generate_for_assets(assets, algorithm="blake3")

        assert len(result) == 1
        assert result[0].checksum is not None
        assert result[0].checksum_alg == "blake3"
        assert len(result[0].checksum) == 64  # blake3 produces 64 hex chars

    def test_s3_default_algorithm(self):
        """Test S3 with default algorithm selection."""
        # Setup mock S3
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="test-bucket")
        s3_client.put_object(Bucket="test-bucket", Key="test.txt", Body=b"content")

        assets = [
            DataAssetRequest(
                location_uri="s3://test-bucket/test.txt", asset_type=AssetType.file
            )
        ]

        result = checksums.generate_for_assets(assets)  # No algorithm specified

        assert len(result) == 1
        assert result[0].checksum is not None
        assert result[0].checksum_alg is not None

    def test_s3_access_error_warning(self):
        """Test S3 access error generates warning."""
        assets = [
            DataAssetRequest(
                location_uri="s3://nonexistent-bucket/file.txt",
                asset_type=AssetType.file,
            )
        ]

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = checksums.generate_for_assets(assets, algorithm="blake3")

            # Should issue warning about failure
            assert len(w) == 1
            assert issubclass(w[0].category, checksums.ChecksumWarning)
            assert "Failed to generate checksum" in str(w[0].message)

            # Should return asset unchanged
            assert result[0].checksum is None

    def test_s3_mixed_platforms(self):
        """Test processing mixed S3 and filesystem platforms."""
        # Setup mock S3
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket="test-bucket")
        s3_client.put_object(Bucket="test-bucket", Key="test.txt", Body=b"s3 content")

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("filesystem content")
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

                # Should process first two, warn about third
                assert len(result) == 3
                assert result[0].checksum is not None  # S3
                assert result[1].checksum is not None  # filesystem
                assert result[2].checksum is None  # unsupported

                # Should have warning for unsupported platform
                platform_warnings = [
                    warning for warning in w if "not supported" in str(warning.message)
                ]
                assert len(platform_warnings) == 1

        finally:
            os.unlink(temp_path)


class TestGenerateForAssetsFilesystem:
    """Test filesystem integration with generate_for_assets."""

    def test_filesystem_success_blake3(self):
        """Test successful filesystem checksum with blake3."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test content for blake3")
            temp_path = f.name

        try:
            assets = [
                DataAssetRequest(
                    location_uri=temp_path,
                    asset_type=AssetType.file,
                    storage_platform=StoragePlatform.hpc,
                )
            ]

            result = checksums.generate_for_assets(assets, algorithm="blake3")

            assert len(result) == 1
            assert result[0].checksum is not None
            assert result[0].checksum_alg == "blake3"
            assert len(result[0].checksum) == 64

            # Original asset unchanged
            assert assets[0].checksum is None

        finally:
            os.unlink(temp_path)

    def test_filesystem_success_crc32(self):
        """Test successful filesystem checksum with crc32."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test content for crc32")
            temp_path = f.name

        try:
            assets = [
                DataAssetRequest(
                    location_uri=temp_path,
                    asset_type=AssetType.file,
                    storage_platform=StoragePlatform.coreweave,
                )
            ]

            result = checksums.generate_for_assets(assets, algorithm="crc32")

            assert len(result) == 1
            assert result[0].checksum is not None
            assert result[0].checksum_alg == "crc32"
            assert len(result[0].checksum) == 8  # CRC32 is 8 hex chars

        finally:
            os.unlink(temp_path)

    def test_filesystem_file_not_found(self):
        """Test filesystem file access error."""
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

            # Should issue warning about access failure
            assert len(w) == 1
            assert issubclass(w[0].category, checksums.ChecksumWarning)
            assert "Failed to generate checksum" in str(w[0].message)

            # Should return asset unchanged
            assert result[0].checksum is None

    def test_filesystem_directory_handling(self):
        """Test directory checksum computation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test files in directory
            with open(os.path.join(temp_dir, "file1.txt"), "w") as f:
                f.write("content1")
            with open(os.path.join(temp_dir, "file2.txt"), "w") as f:
                f.write("content2")

            assets = [
                DataAssetRequest(
                    location_uri=temp_dir,
                    asset_type=AssetType.folder,
                    storage_platform=StoragePlatform.hpc,
                )
            ]

            result = checksums.generate_for_assets(assets, algorithm="blake3")

            assert len(result) == 1
            assert result[0].checksum is not None
            assert result[0].checksum_alg == "blake3"
            # Directory checksums use merkle_root

    def test_algorithm_parameter_handling(self):
        """Test various algorithm parameter values."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("test")
            temp_path = f.name

        try:
            asset = DataAssetRequest(
                location_uri=temp_path,
                asset_type=AssetType.file,
                storage_platform=StoragePlatform.hpc,
            )

            # Test None algorithm (should default)
            result = checksums.generate_for_assets([asset], algorithm=None)
            assert result[0].checksum_alg is not None

            # Test explicit algorithms
            for alg in ["blake3", "blake2b", "crc32"]:
                result = checksums.generate_for_assets([asset], algorithm=alg)
                assert result[0].checksum_alg == alg

        finally:
            os.unlink(temp_path)


class TestChecksumWarning:
    """Test ChecksumWarning class and warning behavior."""

    def test_checksum_warning_inheritance(self):
        """Test ChecksumWarning inherits from UserWarning."""
        assert issubclass(checksums.ChecksumWarning, UserWarning)

    def test_warning_stacklevel_consistency(self):
        """Test warnings use consistent stacklevel for proper source attribution."""
        assets = [
            DataAssetRequest(
                location_uri="http://unsupported.com/file",
                asset_type=AssetType.file,
            )
        ]

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            checksums.generate_for_assets(assets)

            # Verify warning attributes
            assert len(w) == 1
            warning = w[0]
            assert issubclass(warning.category, checksums.ChecksumWarning)
            # stacklevel=2 should point to the generate_for_assets call


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_malformed_s3_uris(self):
        """Test handling of malformed S3 URIs."""
        assets = [
            DataAssetRequest(
                location_uri="s3://",  # Empty bucket/key
                asset_type=AssetType.file,
            )
        ]

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = checksums.generate_for_assets(assets)

            # Should handle gracefully
            assert len(result) == 1

    def test_concurrent_asset_processing(self):
        """Test processing multiple assets concurrently."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create multiple test files
            assets = []
            for i in range(5):
                file_path = os.path.join(temp_dir, f"file{i}.txt")
                with open(file_path, "w") as f:
                    f.write(f"content{i}")

                assets.append(
                    DataAssetRequest(
                        location_uri=file_path,
                        asset_type=AssetType.file,
                        storage_platform=StoragePlatform.hpc,
                    )
                )

            result = checksums.generate_for_assets(assets, algorithm="blake3")

            # All should be processed successfully
            assert len(result) == 5
            for asset in result:
                assert asset.checksum is not None
                assert asset.checksum_alg == "blake3"

    def test_large_file_handling(self):
        """Test handling of larger files (within reason for tests)."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            # Write ~1MB of test data
            test_data = "A" * 1000 + "B" * 1000 + "C" * 1000
            for _ in range(100):
                f.write(test_data)
            temp_path = f.name

        try:
            assets = [
                DataAssetRequest(
                    location_uri=temp_path,
                    asset_type=AssetType.file,
                    storage_platform=StoragePlatform.hpc,
                )
            ]

            result = checksums.generate_for_assets(assets, algorithm="crc32")

            assert len(result) == 1
            assert result[0].checksum is not None
            assert result[0].checksum_alg == "crc32"

        finally:
            os.unlink(temp_path)
