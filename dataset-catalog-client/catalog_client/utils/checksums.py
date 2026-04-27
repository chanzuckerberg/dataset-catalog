"""Checksum generation utilities for DataAssetRequest objects."""

import warnings

from catalog_client.models.asset import DataAssetRequest, StoragePlatform
from catalog_client.utils.checksum.algorithms import Algorithm
from catalog_client.utils.checksum_generator import checksum


class ChecksumWarning(UserWarning):
    """Warning class for checksum generation issues."""

    pass


UNSUPPORTED_PLATFORMS = {StoragePlatform.external, StoragePlatform.other}


def _determine_platform(asset: DataAssetRequest) -> StoragePlatform | None:
    if asset.storage_platform:
        if asset.storage_platform not in UNSUPPORTED_PLATFORMS:
            return asset.storage_platform
        return None

    return _detect_platform(asset.location_uri)


def _detect_platform(location_uri: str) -> StoragePlatform | None:
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


def generate_for_assets(
    assets: list[DataAssetRequest],
    algorithm: Algorithm | None = None,
    compute_if_no_s3_checksum: bool = True,
) -> list[DataAssetRequest]:
    """Generate checksums for assets on supported storage platforms.

    Args:
        assets: List of assets to process
        algorithm: Checksum algorithm. If None, defaults to blake3 except for S3 where existing CRC32 is preferred.
        compute_if_no_s3_checksum: If True, compute checksum by downloading S3 objects
                                  when no existing S3 checksum is available. If False,
                                  skip S3 objects without existing checksums.

    Returns:
        New list with checksums populated for supported assets.
        Issues warnings for unsupported platforms or failures.

    Supported platforms: s3, hpc, coreweave
    """
    if not assets:
        return []

    result = []
    for asset in assets:
        # Create copy to avoid modifying original
        asset_copy = DataAssetRequest(**asset.model_dump())

        # Skip if already has checksum
        if asset_copy.checksum is not None:
            result.append(asset_copy)
            continue

        platform = _determine_platform(asset_copy)
        print(platform)

        if platform is None:
            warnings.warn(
                f"Storage platform for '{asset_copy.location_uri}' not supported for checksum generation",
                ChecksumWarning,
                stacklevel=2,
            )
            result.append(asset_copy)
            continue

        try:
            path = asset_copy.location_uri
            hash_result = checksum(
                path, algorithm=algorithm, use_stored=compute_if_no_s3_checksum
            )
            print(hash_result)

            if hash_result is not None:
                asset_copy.checksum = (
                    hash_result.merkle_root
                    if hash_result.is_directory
                    else hash_result.file_hash
                )
                asset_copy.checksum_alg = hash_result.algorithm

        except Exception as e:
            warnings.warn(
                f"Failed to generate checksum for '{asset_copy.location_uri}': {e}",
                ChecksumWarning,
                stacklevel=2,
            )

        result.append(asset_copy)

    return result
