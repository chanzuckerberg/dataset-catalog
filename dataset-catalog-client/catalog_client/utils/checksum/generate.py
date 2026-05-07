import logging
import warnings

import boto3

from catalog_client.models.asset import AssetType, DataAssetRequest, StoragePlatform
from catalog_client.utils.checksum.algorithm import Algorithm
from catalog_client.utils.checksum.hashing import compute_checksum_localfs, compute_checksum_s3
from catalog_client.utils.checksum.models import ChecksumResult, LocationChecksum
from catalog_client.utils.checksum.s3 import (
    _fetch_all_s3_stored_checksums,
    _find_common_algorithm_in_folder,
    _parse_s3_uri,
    _select_best_algorithm,
)


class ChecksumWarning(UserWarning):
    pass


UNSUPPORTED_PLATFORMS = {StoragePlatform.external, StoragePlatform.other}


def _determine_platform(storage_platform: StoragePlatform | None) -> StoragePlatform | None:
    if storage_platform and storage_platform not in UNSUPPORTED_PLATFORMS:
        return storage_platform
    return None


def detect_and_cache_for_s3(
    location_uri: str,
    asset_type: AssetType,
    algorithm: Algorithm | None,
    cached_results: dict[str, ChecksumResult],
    s3_client,
) -> tuple[Algorithm | None, bool]:
    has_cached_folder_children = False
    detected_algorithm = algorithm
    if asset_type == AssetType.file:
        bucket, key = _parse_s3_uri(location_uri)
        all_checksums = _fetch_all_s3_stored_checksums(bucket, key, s3_client)
        if algorithm is None:
            if all_checksums and (detected_algorithm := _select_best_algorithm(set(all_checksums.keys()))):
                cached_results[location_uri] = all_checksums[detected_algorithm]
        elif algorithm in all_checksums:
            cached_results[location_uri] = all_checksums[algorithm]
    elif asset_type == AssetType.folder:
        _raw_algo, cached_children = _find_common_algorithm_in_folder(location_uri, s3_client)
        common_algorithm = Algorithm(_raw_algo) if _raw_algo is not None else None
        if algorithm is None:
            detected_algorithm = common_algorithm
            if detected_algorithm is not None:
                cached_results.update(cached_children)
        elif common_algorithm == algorithm:
            cached_results.update(cached_children)
            has_cached_folder_children = True
    return detected_algorithm, has_cached_folder_children


def compute_for_s3(
    location_uri: str,
    asset_type: AssetType,
    algorithm: Algorithm | None,
    cached_results: dict[str, ChecksumResult],
    s3_client,
    compute_if_no_s3_checksum: bool,
) -> ChecksumResult | None:
    detected_algorithm, has_cached_folder_children = detect_and_cache_for_s3(
        location_uri, asset_type, algorithm, cached_results, s3_client
    )
    if detected_algorithm and location_uri in cached_results:
        return cached_results[location_uri]

    elif not compute_if_no_s3_checksum and not has_cached_folder_children:
        return None
    else:
        return compute_checksum_s3(
            location_uri,
            algorithm=detected_algorithm or Algorithm.blake3,
            s3_client=s3_client,
            use_stored=False,
            cached_results=cached_results,
        )


def for_location(
    location_uri: str,
    asset_type: AssetType,
    storage_platform: StoragePlatform | None = None,
    algorithm: Algorithm | None = None,
    s3_client=None,
    cached_results: dict[str, ChecksumResult] | None = None,
    compute_if_no_s3_checksum: bool = False,
) -> LocationChecksum:
    if not location_uri:
        logging.error("Can't generate checksum when location is None")
        return LocationChecksum()

    if not (platform := _determine_platform(storage_platform)):
        warnings.warn(
            f"StoragePlatform of {location_uri} not supported for checksum generation", ChecksumWarning, stacklevel=2
        )
        return LocationChecksum()

    is_s3 = platform == StoragePlatform.s3
    if is_s3 and s3_client is None:
        logging.error("No s3 client provided for s3 data access")
        return LocationChecksum()

    try:
        if is_s3:
            cached_results = {} if cached_results is None else cached_results
            hash_result = compute_for_s3(
                location_uri, asset_type, algorithm, cached_results, s3_client, compute_if_no_s3_checksum
            )
        else:
            hash_result = compute_checksum_localfs(location_uri, algorithm=algorithm or Algorithm.blake3)

        if hash_result is not None:
            value = hash_result.merkle_root if hash_result.is_directory else hash_result.file_hash
            return LocationChecksum(value=value, algorithm=hash_result.algorithm)

    except Exception as e:
        warnings.warn(
            f"Failed to generate checksum for '{location_uri}': {e}",
            ChecksumWarning,
            stacklevel=2,
        )
    return LocationChecksum()


def for_assets(
    assets: list[DataAssetRequest],
    algorithm: Algorithm | None = None,
    compute_if_no_s3_checksum: bool = True,
    s3_client=None,
) -> list[DataAssetRequest]:
    """
    Populate checksums on a list of DataAssetRequest objects.

    algorithm=None auto-detects from stored S3 checksums (highest priority wins),
    falling back to blake3 if none exist. Non-S3 assets always compute locally.

    compute_if_no_s3_checksum=False skips S3 assets that have no stored checksum
    rather than downloading them. Has no effect on non-S3 assets.

    Unsupported platforms (external, other, None) are passed through with a
    ChecksumWarning. Failures also warn and pass the asset through unchanged.
    """
    if not assets:
        return []

    result = []
    cached_results: dict[str, ChecksumResult] = {}
    s3_client = s3_client or boto3.client("s3")

    for asset in assets:
        if asset.checksum is not None:
            result.append(asset)
            continue

        result_checksum = for_location(
            asset.location_uri,
            asset.asset_type,
            asset.storage_platform,
            algorithm,
            s3_client,
            cached_results,
            compute_if_no_s3_checksum=compute_if_no_s3_checksum,
        )

        if result_checksum:
            asset.checksum = result_checksum.value
            asset.checksum_alg = result_checksum.algorithm

        result.append(asset)

    return result
