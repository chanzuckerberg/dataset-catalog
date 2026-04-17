"""Checksum generation utilities for DataAssetRequest objects."""

from __future__ import annotations

import hashlib
import zlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catalog_client.models.asset import DataAssetRequest

try:
    import blake3
except ImportError:
    blake3 = None  # Will be handled in _HashUtils.blake3


class ChecksumWarning(UserWarning):
    """Warning class for checksum generation issues."""

    pass


class _HashUtils:
    """Hash algorithm implementations."""

    @staticmethod
    def blake3(data: bytes) -> str:
        """Compute blake3 hash of data.

        Args:
            data: Bytes to hash

        Returns:
            Hexadecimal string representation of hash

        Raises:
            ImportError: If blake3 package not available
        """
        if blake3 is None:
            raise ImportError("blake3 package required for blake3 algorithm")
        return blake3.blake3(data).hexdigest()

    @staticmethod
    def blake2b(data: bytes) -> str:
        """Compute blake2b hash of data.

        Args:
            data: Bytes to hash

        Returns:
            Hexadecimal string representation of hash (128 chars)
        """
        return hashlib.blake2b(data).hexdigest()

    @staticmethod
    def blake2s(data: bytes) -> str:
        """Compute blake2s hash of data.

        Args:
            data: Bytes to hash

        Returns:
            Hexadecimal string representation of hash (64 chars)
        """
        return hashlib.blake2s(data).hexdigest()

    @staticmethod
    def crc32(data: bytes) -> str:
        """Compute CRC32 checksum of data.

        Args:
            data: Bytes to checksum

        Returns:
            Hexadecimal string representation of checksum (8 chars)
        """
        return format(zlib.crc32(data) & 0xffffffff, '08x')


def get_supported_algorithms() -> list[str]:
    """Returns list of supported checksum algorithms.

    Returns:
        List of algorithm names: ['blake3', 'blake2b', 'blake2s', 'crc32']
    """
    return ['blake3', 'blake2b', 'blake2s', 'crc32']


def generate_for_assets(
    assets: list[DataAssetRequest],
    algorithm: str | None = None
) -> list[DataAssetRequest]:
    """Generate checksums for assets on supported storage platforms.

    Args:
        assets: List of assets to process
        algorithm: Checksum algorithm ('blake3', 'blake2b', 'blake2s', 'crc32').
                  If None, defaults to blake3 except for S3 where existing CRC32 is preferred.

    Returns:
        New list with checksums populated for supported assets.
        Issues warnings for unsupported platforms or failures.

    Supported platforms: s3, hpc, coreweave
    Supported algorithms: blake3, blake2b, blake2s, crc32
    """
    # TODO: Implement in subsequent tasks
    return assets.copy()
