"""Checksum generation utilities for DataAssetRequest objects."""

from __future__ import annotations

import hashlib
import zlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catalog_client.models.asset import DataAssetRequest, StoragePlatform

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


class _ChecksumBackend:
    """Handles checksum generation for different storage platforms."""

    def _determine_platform(self, asset: DataAssetRequest) -> StoragePlatform | None:
        """Determine storage platform from asset.

        Checks explicit storage_platform first, fallback to URI parsing.

        Args:
            asset: Asset to check platform for

        Returns:
            StoragePlatform if supported, None otherwise
        """
        from catalog_client.models.asset import StoragePlatform

        # Primary: Check explicit storage_platform
        if asset.storage_platform:
            if asset.storage_platform in {
                StoragePlatform.s3,
                StoragePlatform.hpc,
                StoragePlatform.bruno_hpc,
                StoragePlatform.coreweave
            }:
                return asset.storage_platform
            return None

        # Fallback: Parse URI patterns
        return self._detect_platform(asset.location_uri)

    def _detect_platform(self, location_uri: str) -> StoragePlatform | None:
        """Parse URI patterns to detect storage platform.

        Args:
            location_uri: URI to parse

        Returns:
            StoragePlatform if recognized pattern, None otherwise
        """
        from catalog_client.models.asset import StoragePlatform

        if location_uri.startswith(('s3://', 's3a://')):
            return StoragePlatform.s3
        elif '/hpc/' in location_uri:
            return StoragePlatform.hpc
        elif '/bruno_hpc/' in location_uri:
            return StoragePlatform.bruno_hpc
        elif '/coreweave/' in location_uri:
            return StoragePlatform.coreweave
        else:
            return None

    def _compute_filesystem_checksum(self, path: str, algorithm: str) -> tuple[str, str]:
        """Compute checksum for filesystem file.

        Args:
            path: Filesystem path to file
            algorithm: Hash algorithm to use

        Returns:
            Tuple of (checksum_value, checksum_alg)

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If algorithm not supported
        """
        if algorithm not in get_supported_algorithms():
            raise ValueError(f"Unsupported algorithm: {algorithm}")

        chunk_size = 8192

        # Initialize hash objects directly for streaming
        if algorithm == 'blake3':
            if blake3 is None:
                raise ImportError("blake3 package required for blake3 algorithm")
            hash_obj = blake3.blake3()
        elif algorithm == 'blake2b':
            hash_obj = hashlib.blake2b()
        elif algorithm == 'blake2s':
            hash_obj = hashlib.blake2s()
        elif algorithm == 'crc32':
            crc_value = 0
        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")

        # Stream file in chunks for memory efficiency
        with open(path, 'rb') as f:
            while chunk := f.read(chunk_size):
                if algorithm == 'crc32':
                    # CRC32 needs cumulative value
                    crc_value = zlib.crc32(chunk, crc_value)
                else:
                    hash_obj.update(chunk)

        # Return final hash value
        if algorithm == 'crc32':
            checksum_value = format(crc_value & 0xffffffff, '08x')
        else:
            checksum_value = hash_obj.hexdigest()

        return checksum_value, algorithm


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
