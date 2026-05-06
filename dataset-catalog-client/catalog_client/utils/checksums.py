"""Checksum generation utilities for DataAssetRequest objects."""

import base64
import hashlib
import warnings
import zlib
from typing import Any

import blake3
import boto3

from catalog_client import AssetType
from catalog_client.models.asset import DataAssetRequest, StoragePlatform


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
        return format(zlib.crc32(data) & 0xFFFFFFFF, "08x")


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
        # Primary: Check explicit storage_platform
        if asset.storage_platform:
            # Exclude unsupported platforms
            if asset.storage_platform not in {
                StoragePlatform.external,
                StoragePlatform.other,
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
        if location_uri.startswith(("s3://", "s3a://")):
            return StoragePlatform.s3
        elif "/hpc/" in location_uri:
            return StoragePlatform.hpc
        elif "/bruno_hpc/" in location_uri:
            return StoragePlatform.bruno_hpc
        elif "/coreweave/" in location_uri:
            return StoragePlatform.coreweave
        else:
            return None

    def _compute_filesystem_checksum(
        self, path: str, algorithm: str
    ) -> tuple[str, str]:
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
        hash_obj: Any
        if algorithm == "blake3":
            if blake3 is None:
                raise ImportError("blake3 package required for blake3 algorithm")
            hash_obj = blake3.blake3()
        elif algorithm == "blake2b":
            hash_obj = hashlib.blake2b()
        elif algorithm == "blake2s":
            hash_obj = hashlib.blake2s()
        elif algorithm == "crc32":
            crc_value = 0
        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")

        # Stream file in chunks for memory efficiency
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                if algorithm == "crc32":
                    # CRC32 needs cumulative value
                    crc_value = zlib.crc32(chunk, crc_value)
                else:
                    hash_obj.update(chunk)

        # Return final hash value
        if algorithm == "crc32":
            checksum_value = format(crc_value & 0xFFFFFFFF, "08x")
        else:
            checksum_value = hash_obj.hexdigest()

        return checksum_value, algorithm

    def _compute_s3_checksum(
        self, uri: str, algorithm: str | None, compute_if_no_s3_checksum: bool = True
    ) -> tuple[str | None, str | None]:
        """Compute checksum for S3 object with CRC32 optimization.

        When algorithm is None, attempts to use existing S3 CRC32 checksum.
        Otherwise downloads object and computes requested algorithm.

        Args:
            uri: S3 URI (s3://bucket/key)
            algorithm: Hash algorithm or None for CRC32 optimization
            compute_if_no_s3_checksum: If False, does not compute S3 checksum is not found

        Returns:
            Tuple of (checksum_value, checksum_alg) or (None, None) if
            compute_if_no_s3_checksum=False and no S3 checksum exists

        Raises:
            Various boto3 exceptions: For S3 access errors
        """

        # Parse S3 URI
        uri_parts = uri.replace("s3://", "").replace("s3a://", "").split("/", 1)
        bucket = uri_parts[0]
        key = uri_parts[1] if len(uri_parts) > 1 else ""

        s3_client = boto3.client("s3")

        # Try CRC32 optimization when algorithm is None
        if not algorithm:
            try:
                # Get object metadata
                response = s3_client.head_object(
                    Bucket=bucket, Key=key, ChecksumMode="ENABLED"
                )

                # Check for existing CRC32 checksum
                if "ChecksumCRC32" in response:
                    # Convert base64 CRC32 to hex
                    crc32_b64 = response["ChecksumCRC32"]
                    crc32_bytes = base64.b64decode(crc32_b64)
                    crc32_hex = crc32_bytes.hex()
                    return crc32_hex, "crc32"

            except Exception:
                # Fall through to download method if allowed
                pass

            # If no S3 checksum found and compute_if_no_s3_checksum=False, return None
            if not compute_if_no_s3_checksum:
                return None, None

        # Don't compute if flag is False and specific algorithm requested
        if not compute_if_no_s3_checksum and algorithm:
            return None, None

        # Fallback: Download object and compute hash
        target_algorithm = algorithm or "blake3"

        if target_algorithm not in get_supported_algorithms():
            raise ValueError(f"Unsupported algorithm: {target_algorithm}")

        hash_func = getattr(_HashUtils, target_algorithm)

        # Download object
        response = s3_client.get_object(Bucket=bucket, Key=key)
        data = response["Body"].read()

        return hash_func(data), target_algorithm


def get_supported_algorithms() -> list[str]:
    """Returns list of supported checksum algorithms.

    Returns:
        List of algorithm names: ['blake3', 'blake2b', 'blake2s', 'crc32']
    """
    return ["blake3", "blake2b", "blake2s", "crc32"]


def generate_for_assets(
    assets: list[DataAssetRequest],
    algorithm: str | None = None,
    compute_if_no_s3_checksum: bool = True,
) -> list[DataAssetRequest]:
    """Generate checksums for assets on supported storage platforms.

    Args:
        assets: List of assets to process
        algorithm: Checksum algorithm ('blake3', 'blake2b', 'blake2s', 'crc32').
                  If None, defaults to blake3 except for S3 where existing CRC32 is preferred.
        compute_if_no_s3_checksum: If True, compute checksum by downloading S3 objects
                                  when no existing S3 checksum is available. If False,
                                  skip S3 objects without existing checksums.

    Returns:
        New list with checksums populated for supported assets.
        Issues warnings for unsupported platforms or failures.

    Supported platforms: s3, hpc, coreweave
    Supported algorithms: blake3, blake2b, blake2s, crc32

    TODO: Expand checksum generation to support folder assets (AssetType.folder).
          Current implementation only handles files (AssetType.file).
    """
    if not assets:
        return []

    backend = _ChecksumBackend()
    result = []

    for asset in assets:
        # Create copy to avoid modifying original
        asset_copy = DataAssetRequest(**asset.model_dump())

        # Skip if already has checksum
        if asset_copy.checksum is not None or asset_copy.asset_type is AssetType.folder:
            result.append(asset_copy)
            continue

        # Determine platform
        platform = backend._determine_platform(asset_copy)

        if platform is None:
            warnings.warn(
                f"Storage platform for '{asset_copy.location_uri}' not supported for checksum generation",
                ChecksumWarning,
                stacklevel=2,
            )
            result.append(asset_copy)
            continue

        try:
            # Generate checksum based on platform
            if platform == StoragePlatform.s3:
                checksum_value, checksum_alg = backend._compute_s3_checksum(
                    asset_copy.location_uri, algorithm, compute_if_no_s3_checksum
                )
            else:
                # Filesystem platforms (hpc, bruno_hpc, coreweave)
                target_algorithm = algorithm or "blake3"
                checksum_value, checksum_alg = backend._compute_filesystem_checksum(
                    asset_copy.location_uri, target_algorithm
                )

            # Update asset copy with checksum if computed
            if checksum_value is not None:
                asset_copy.checksum = checksum_value
                asset_copy.checksum_alg = checksum_alg

        except Exception as e:
            warnings.warn(
                f"Failed to generate checksum for '{asset_copy.location_uri}': {e}",
                ChecksumWarning,
                stacklevel=2,
            )

        result.append(asset_copy)

    return result
