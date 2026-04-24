"""Checksum generation utilities for DataAssetRequest objects."""

import base64
import hashlib
import warnings
import zlib
from typing import Any

import boto3

from catalog_client import AssetType
from catalog_client.models.asset import DataAssetRequest, StoragePlatform

try:
    import blake3
except ImportError:
    blake3 = None


class ChecksumWarning(UserWarning):
    """Warning class for checksum generation issues."""

    pass


class _HashUtils:
    """Hash algorithm implementations."""

    @staticmethod
    def crc32(data: bytes) -> str:
        """Compute CRC32 checksum of data.

        Args:
            data: Bytes to checksum

        Returns:
            Hexadecimal string representation of checksum (8 chars)
        """
        return format(zlib.crc32(data) & 0xFFFFFFFF, "08x")

    @staticmethod
    def get_checksum_algorithm_mapping() -> dict[str, Any]:
        """Returns a map of supported checksum algorithms, and their implementation.
        Returns:
            Mapping of checksum algorithm to their implementation
        """
        return {
            "blake3": blake3.blake3(),
            "blake2b": hashlib.blake2b(),
            "crc32": _HashUtils.crc32,
        }


class _ChecksumBackend:
    """Handles checksum generation for different storage platforms."""

    UNSUPPORTED_PLATFORMS = {StoragePlatform.external, StoragePlatform.other}

    def _determine_platform(self, asset: DataAssetRequest) -> StoragePlatform | None:
        """Determine storage platform from asset. Checks explicit storage_platform first, fallback to URI parsing.

        Args:
            asset: Asset to check platform for

        Returns:
            StoragePlatform if supported, None otherwise
        """
        if asset.storage_platform:
            if asset.storage_platform not in self.UNSUPPORTED_PLATFORMS:
                return asset.storage_platform
            return None

        # Fallback: Parse URI patterns
        return self._detect_platform(asset.location_uri)

    @classmethod
    def _detect_platform(cls, location_uri: str) -> StoragePlatform | None:
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

    @classmethod
    def _compute_filesystem_checksum(cls, path: str, algorithm: str) -> tuple[str, str]:
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
        hash_func = _HashUtils.get_checksum_algorithm_mapping().get(algorithm)
        if hash_func is None:
            raise ValueError(f"Unsupported algorithm: {algorithm}")
        checksum_value = hash_func(path)

        return checksum_value, algorithm

    def _compute_s3_checksum(
        self, uri: str, algorithm: str | None, compute_if_no_s3_checksum: bool = True
    ) -> tuple[str | None, str | None]:
        """Compute checksum for S3 object with CRC32 optimization.

        When algorithm is None, attempts to use existing S3 checksum.
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

        if not compute_if_no_s3_checksum:
            return None, None

        # Fallback: Download object and compute hash
        target_algorithm = algorithm or "blake3"
        hash_func = _HashUtils.get_checksum_algorithm_mapping().get(target_algorithm)
        if not hash_func:
            raise ValueError(f"Unsupported algorithm: {target_algorithm}")

        # Download object
        response = s3_client.get_object(Bucket=bucket, Key=key)
        data = response["Body"].read()

        return hash_func(data), target_algorithm


def get_supported_algorithms() -> list[str]:
    """Returns list of supported checksum algorithms.

    Returns:
        List of algorithm names
    """
    return list(_HashUtils.get_checksum_algorithm_mapping().keys())


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
