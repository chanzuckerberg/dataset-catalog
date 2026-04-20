"""Tests for checksum utilities module."""

from catalog_client.models.asset import DataAssetRequest, AssetType, StoragePlatform
from catalog_client.utils.checksums import _HashUtils


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
