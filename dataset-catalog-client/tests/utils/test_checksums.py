"""Tests for checksum utilities module."""

import os
import tempfile

import pytest

from catalog_client.models.asset import DataAssetRequest, AssetType, StoragePlatform
from catalog_client.utils.checksums import _ChecksumBackend, _HashUtils


class TestHashUtils:
    """Test hash algorithm implementations."""

    def test_blake3_algorithm(self):
        """Test blake3 produces expected output."""
        data = b"hello world"
        result = _HashUtils.blake3(data)
        # blake3 of "hello world" is consistent
        assert isinstance(result, str)
        assert len(result) == 64  # blake3 default 256-bit = 64 hex chars

        # Same input produces same output
        assert _HashUtils.blake3(data) == result

    def test_blake2b_algorithm(self):
        """Test blake2b produces expected output."""
        data = b"hello world"
        result = _HashUtils.blake2b(data)
        assert isinstance(result, str)
        assert len(result) == 128  # blake2b default 512-bit = 128 hex chars
        assert _HashUtils.blake2b(data) == result

    def test_blake2s_algorithm(self):
        """Test blake2s produces expected output."""
        data = b"hello world"
        result = _HashUtils.blake2s(data)
        assert isinstance(result, str)
        assert len(result) == 64  # blake2s default 256-bit = 64 hex chars
        assert _HashUtils.blake2s(data) == result

    def test_crc32_algorithm(self):
        """Test crc32 produces expected output."""
        data = b"hello world"
        result = _HashUtils.crc32(data)
        assert isinstance(result, str)
        assert len(result) == 8  # crc32 is 32-bit = 8 hex chars
        assert _HashUtils.crc32(data) == result

    def test_algorithm_deterministic(self):
        """Test all algorithms are deterministic."""
        data = b"test data for consistency"

        assert _HashUtils.blake3(data) == _HashUtils.blake3(data)
        assert _HashUtils.blake2b(data) == _HashUtils.blake2b(data)
        assert _HashUtils.blake2s(data) == _HashUtils.blake2s(data)
        assert _HashUtils.crc32(data) == _HashUtils.crc32(data)


class TestCheckSumBackend:
    """Test _ChecksumBackend platform detection."""

    def test_explicit_storage_platform_takes_precedence(self):
        """Test explicit storage_platform overrides URI detection."""
        from catalog_client.utils.checksums import _ChecksumBackend
        backend = _ChecksumBackend()
        asset = DataAssetRequest(
            location_uri="file:///local/path",
            asset_type=AssetType.file,
            storage_platform=StoragePlatform.s3
        )
        platform = backend._determine_platform(asset)
        assert platform == StoragePlatform.s3

    def test_uri_pattern_detection_s3(self):
        """Test S3 URI pattern detection."""
        from catalog_client.utils.checksums import _ChecksumBackend
        backend = _ChecksumBackend()
        asset = DataAssetRequest(
            location_uri="s3://bucket/key",
            asset_type=AssetType.file
        )
        platform = backend._determine_platform(asset)
        assert platform == StoragePlatform.s3

    def test_uri_pattern_detection_s3a(self):
        """Test S3A URI pattern detection."""
        from catalog_client.utils.checksums import _ChecksumBackend
        backend = _ChecksumBackend()
        asset = DataAssetRequest(
            location_uri="s3a://bucket/key",
            asset_type=AssetType.file
        )
        platform = backend._determine_platform(asset)
        assert platform == StoragePlatform.s3

    def test_uri_pattern_detection_hpc(self):
        """Test HPC URI pattern detection."""
        from catalog_client.utils.checksums import _ChecksumBackend
        backend = _ChecksumBackend()
        asset = DataAssetRequest(
            location_uri="/hpc/data/file.txt",
            asset_type=AssetType.file
        )
        platform = backend._determine_platform(asset)
        assert platform == StoragePlatform.hpc

    def test_uri_pattern_detection_bruno_hpc(self):
        """Test Bruno HPC URI pattern detection."""
        from catalog_client.utils.checksums import _ChecksumBackend
        backend = _ChecksumBackend()
        asset = DataAssetRequest(
            location_uri="/bruno_hpc/data/file.txt",
            asset_type=AssetType.file
        )
        platform = backend._determine_platform(asset)
        assert platform == StoragePlatform.bruno_hpc

    def test_uri_pattern_detection_coreweave(self):
        """Test CoreWeave URI pattern detection."""
        from catalog_client.utils.checksums import _ChecksumBackend
        backend = _ChecksumBackend()
        asset = DataAssetRequest(
            location_uri="/coreweave/data/file.txt",
            asset_type=AssetType.file
        )
        platform = backend._determine_platform(asset)
        assert platform == StoragePlatform.coreweave

    def test_unsupported_platform_returns_none(self):
        """Test unsupported platform returns None."""
        from catalog_client.utils.checksums import _ChecksumBackend
        backend = _ChecksumBackend()
        asset = DataAssetRequest(
            location_uri="http://example.com/file.txt",
            asset_type=AssetType.file
        )
        platform = backend._determine_platform(asset)
        assert platform is None

    def test_compute_filesystem_checksum_blake3(self):
        """Test filesystem checksum computation with blake3."""
        backend = _ChecksumBackend()

        # Create temporary test file
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("hello world")
            temp_path = f.name

        try:
            checksum_value, checksum_alg = backend._compute_filesystem_checksum(
                temp_path, 'blake3'
            )

            # Verify result format
            assert isinstance(checksum_value, str)
            assert checksum_alg == 'blake3'
            assert len(checksum_value) == 64  # blake3 256-bit = 64 hex chars

            # Verify it matches direct hash computation
            expected = _HashUtils.blake3(b"hello world")
            assert checksum_value == expected

        finally:
            os.unlink(temp_path)

    def test_compute_filesystem_checksum_crc32(self):
        """Test filesystem checksum computation with crc32."""
        backend = _ChecksumBackend()

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test data")
            temp_path = f.name

        try:
            checksum_value, checksum_alg = backend._compute_filesystem_checksum(
                temp_path, 'crc32'
            )

            assert isinstance(checksum_value, str)
            assert checksum_alg == 'crc32'
            assert len(checksum_value) == 8  # crc32 32-bit = 8 hex chars

            expected = _HashUtils.crc32(b"test data")
            assert checksum_value == expected

        finally:
            os.unlink(temp_path)

    def test_compute_filesystem_checksum_file_not_found(self):
        """Test filesystem checksum with non-existent file."""
        backend = _ChecksumBackend()

        with pytest.raises(FileNotFoundError):
            backend._compute_filesystem_checksum('/nonexistent/file', 'blake3')

    def test_compute_filesystem_checksum_unsupported_algorithm(self):
        """Test filesystem checksum with unsupported algorithm."""
        backend = _ChecksumBackend()

        with tempfile.NamedTemporaryFile() as f:
            with pytest.raises(ValueError, match="Unsupported algorithm: md5"):
                backend._compute_filesystem_checksum(f.name, 'md5')
