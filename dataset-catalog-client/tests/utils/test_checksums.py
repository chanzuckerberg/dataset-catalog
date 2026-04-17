"""Tests for checksum utilities module."""

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
