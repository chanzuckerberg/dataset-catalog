"""Checksum generation utilities for DataAssetRequest objects."""

import warnings

import boto3

from catalog_client.models.asset import AssetType, DataAssetRequest, StoragePlatform
from catalog_client.utils.checksum.algorithms import Algorithm
from catalog_client.utils.checksum.models import ChecksumResult
from catalog_client.utils.generator import (
    _fetch_all_s3_stored_checksums,
    _find_common_algorithm_in_folder,
    _parse_s3_uri,
    _select_best_algorithm,
    checksum,
)


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
        assets: List of assets to process.
        algorithm: Checksum algorithm. If None, the system will:
            - For S3 files: detect the stored checksum algorithm (preferring
              computed/metadata over native, by priority).
            - For S3 folders: find the best algorithm shared by ALL children
              (set intersection, preferring computed over native).
            - Fall back to blake3 if no stored checksum is found.
        compute_if_no_s3_checksum: If True (default), compute checksum by
            downloading S3 objects when no stored checksum exists. If False,
            skip S3 objects without stored checksums. This flag only affects
            S3 assets; non-S3 assets always proceed to computation.

    Returns:
        New list with checksums populated for supported assets.
        Issues warnings for unsupported platforms or failures.

    Supported platforms: s3, hpc, coreweave
    """
    if not assets:
        return []

    result = []
    cached_results: dict[str, ChecksumResult] = {}
    s3_client = None

    for asset in assets:
        if asset.checksum is not None:
            result.append(asset)
            continue

        asset_copy = DataAssetRequest(**asset.model_dump())
        platform = _determine_platform(asset_copy)

        if platform is None:
            warnings.warn(
                f"Storage platform for '{asset_copy.location_uri}' "
                f"not supported for checksum generation",
                ChecksumWarning,
                stacklevel=2,
            )
            result.append(asset_copy)
            continue

        is_s3 = platform == StoragePlatform.s3
        detected_algorithm = algorithm

        if is_s3 and s3_client is None:
            s3_client = boto3.client("s3")

        try:
            # ── DETECTION PHASE (S3 only, algorithm=None) ──────────────
            if algorithm is None and is_s3:
                if asset_copy.asset_type == AssetType.file:
                    bucket, key = _parse_s3_uri(asset_copy.location_uri)
                    all_checksums = _fetch_all_s3_stored_checksums(
                        bucket, key, s3_client
                    )
                    if all_checksums:
                        detected_algorithm = _select_best_algorithm(
                            set(all_checksums.keys())
                        )
                        cached_results[asset_copy.location_uri] = all_checksums[
                            detected_algorithm
                        ]

                elif asset_copy.asset_type == AssetType.folder:
                    detected_algorithm, cached_children = (
                        _find_common_algorithm_in_folder(
                            asset_copy.location_uri, s3_client
                        )
                    )
                    if detected_algorithm is not None:
                        cached_results.update(cached_children)

            # ── COMPUTE PHASE ──────────────────────────────────────────
            if asset_copy.location_uri in cached_results:
                hash_result = cached_results[asset_copy.location_uri]

            else:
                # Gate S3 assets by compute_if_no_s3_checksum flag
                if is_s3 and not compute_if_no_s3_checksum:
                    result.append(asset_copy)
                    continue

                effective_algorithm = detected_algorithm or "blake3"

                hash_result = checksum(
                    asset_copy.location_uri,
                    algorithm=effective_algorithm,
                    s3_client=s3_client,
                    use_stored=False,
                    cached_results=cached_results,
                )

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
