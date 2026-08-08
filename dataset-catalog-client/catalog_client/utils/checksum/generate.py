import logging
import warnings
from dataclasses import dataclass
from typing import TypeVar

from catalog_client.models.asset import AssetType, DataAssetRequest, StoragePlatform
from catalog_client.utils.checksum.algorithm import Algorithm, default_algorithm
from catalog_client.utils.checksum.hashing import (
    compute_checksum_localfs,
    compute_checksum_s3,
)
from catalog_client.utils.checksum.models import ChecksumResult, LocationChecksum
from catalog_client.utils.checksum.s3 import (
    _fetch_all_s3_stored_checksums,
    _find_common_algorithm_in_folder,
    _parse_s3_uri,
    _select_best_algorithm,
)

logger = logging.getLogger(__name__)


class ChecksumWarning(UserWarning):
    pass


UNSUPPORTED_PLATFORMS = {StoragePlatform.external, StoragePlatform.other}

# for_assets preserves the caller's concrete asset type (DataAssetResponse is a
# DataAssetRequest subclass that widens storage_platform to optional).
AssetT = TypeVar("AssetT", bound=DataAssetRequest)


def _determine_platform(
    storage_platform: StoragePlatform | None,
) -> StoragePlatform | None:
    if storage_platform and storage_platform not in UNSUPPORTED_PLATFORMS:
        return storage_platform
    return None


def _skip(message: str) -> None:
    """
    Report a location we are not going to checksum.

    Every skip goes through one mechanism so that a caller filtering on
    ChecksumWarning sees all of them, not just the subset that used to warn
    while the rest went to the root logger.
    """
    logger.debug("Skipping checksum: %s", message)
    warnings.warn(message, ChecksumWarning, stacklevel=3)


@dataclass
class _S3Detection:
    """
    What the detect phase learned about an S3 location.

    Bundled rather than returned as a loose tuple because the compute phase
    needs every field to route correctly; dropping one silently changes
    behaviour (see `has_cached_children`, which previously defaulted to False
    on the auto-detect path and made algorithm=None strictly worse than
    naming the algorithm auto-detection would have chosen).
    """

    algorithm: Algorithm | None
    has_cached_children: bool = False


def detect_and_cache_for_s3(
    location_uri: str,
    asset_type: AssetType,
    algorithm: Algorithm | None,
    cached_results: dict[str, ChecksumResult],
    s3_client,
) -> _S3Detection:
    if asset_type == AssetType.folder:
        common_algorithm, cached_children = _find_common_algorithm_in_folder(
            location_uri, s3_client
        )
        # Children are reusable whenever the algorithm we are going to hash
        # with is the one they all carry — whether that algorithm was named by
        # the caller or discovered here.
        if algorithm is None:
            if common_algorithm is None:
                return _S3Detection(algorithm=None)
            cached_results.update(cached_children)
            return _S3Detection(algorithm=common_algorithm, has_cached_children=True)
        if common_algorithm == algorithm:
            cached_results.update(cached_children)
            return _S3Detection(algorithm=algorithm, has_cached_children=True)
        return _S3Detection(algorithm=algorithm)

    bucket, key = _parse_s3_uri(location_uri)
    all_checksums = _fetch_all_s3_stored_checksums(bucket, key, s3_client)
    if algorithm is None:
        detected = _select_best_algorithm(set(all_checksums.keys()))
        if detected is not None:
            cached_results[location_uri] = all_checksums[detected]
        return _S3Detection(algorithm=detected)
    if algorithm in all_checksums:
        cached_results[location_uri] = all_checksums[algorithm]
    return _S3Detection(algorithm=algorithm)


def compute_for_s3(
    location_uri: str,
    asset_type: AssetType,
    algorithm: Algorithm | None,
    cached_results: dict[str, ChecksumResult],
    s3_client,
    compute_if_no_s3_checksum: bool,
) -> ChecksumResult | None:
    detection = detect_and_cache_for_s3(
        location_uri, asset_type, algorithm, cached_results, s3_client
    )
    if detection.algorithm and location_uri in cached_results:
        return cached_results[location_uri]

    # Assembling a folder digest from already-cached children needs no
    # downloads, so compute_if_no_s3_checksum does not apply to it.
    if not compute_if_no_s3_checksum and not detection.has_cached_children:
        logger.debug(
            "Skipping %s: no stored S3 checksum and compute_if_no_s3_checksum=False",
            location_uri,
        )
        return None

    return compute_checksum_s3(
        location_uri,
        algorithm=detection.algorithm or default_algorithm(),
        s3_client=s3_client,
        use_stored=False,
        cached_results=cached_results,
        is_folder=asset_type == AssetType.folder,
    )


def for_location(
    location_uri: str,
    asset_type: AssetType,
    storage_platform: StoragePlatform | None = None,
    algorithm: Algorithm | None = None,
    s3_client=None,
    cached_results: dict[str, ChecksumResult] | None = None,
    compute_if_no_s3_checksum: bool = True,
) -> LocationChecksum:
    """
    Compute the checksum for a single location.

    Returns an empty (falsy) LocationChecksum when the location is skipped or
    fails; every such case also emits a ChecksumWarning, so a caller can turn
    all of them into errors with
    `warnings.simplefilter("error", ChecksumWarning)`.
    """
    if not location_uri:
        _skip("Cannot generate a checksum for an empty location_uri")
        return LocationChecksum()

    if not (platform := _determine_platform(storage_platform)):
        _skip(
            f"StoragePlatform of {location_uri} not supported for checksum generation"
        )
        return LocationChecksum()

    is_s3 = platform == StoragePlatform.s3
    if is_s3 and s3_client is None:
        _skip(f"No s3_client provided; cannot read {location_uri}")
        return LocationChecksum()

    try:
        if is_s3:
            cached_results = {} if cached_results is None else cached_results
            hash_result = compute_for_s3(
                location_uri,
                asset_type,
                algorithm,
                cached_results,
                s3_client,
                compute_if_no_s3_checksum,
            )
        else:
            hash_result = compute_checksum_localfs(
                location_uri, algorithm=algorithm or default_algorithm()
            )

        if hash_result is not None:
            # content_digest, not merkle_root — the same value this node would
            # contribute to a parent directory. See ChecksumResult.content_digest.
            return LocationChecksum(
                value=hash_result.content_digest, algorithm=hash_result.algorithm
            )

    except Exception as e:
        warnings.warn(
            f"Failed to generate checksum for '{location_uri}': {e}",
            ChecksumWarning,
            stacklevel=2,
        )
    return LocationChecksum()


def for_assets(
    assets: list[AssetT],
    algorithm: Algorithm | None = None,
    compute_if_no_s3_checksum: bool = True,
    s3_client=None,
) -> list[AssetT]:
    """
    Return copies of the given assets with `checksum` and `checksum_alg` populated.

    The input assets are NOT modified: each is shallow-copied via
    `model_copy()`, preserving its concrete type, and the copies are returned.
    Read the results off the returned list.

    algorithm=None auto-detects from stored S3 checksums (highest priority wins),
    falling back to `default_algorithm()` if none exist. Non-S3 assets always
    compute locally.

    compute_if_no_s3_checksum=False skips S3 assets that have no stored checksum
    rather than downloading them. It does not apply to folders whose children
    all carry a stored checksum, since assembling those needs no download, nor
    to non-S3 assets.

    Unsupported platforms (external, other, None) are passed through with a
    ChecksumWarning. Failures also warn and pass the asset through unchanged.
    """
    if not assets:
        return []

    result: list[AssetT] = []
    cached_results: dict[str, ChecksumResult] = {}
    if s3_client is None:
        # Imported here rather than at module scope: boto3/botocore pull in
        # several hundred modules, and `import catalog_client` reaches this
        # module transitively via catalog_client.utils.
        import boto3

        s3_client = boto3.client("s3")

    for asset in assets:
        asset_copy = asset.model_copy()
        if asset_copy.checksum is not None:
            result.append(asset_copy)
            continue

        result_checksum = for_location(
            asset_copy.location_uri,
            asset_copy.asset_type,
            asset_copy.storage_platform,
            algorithm,
            s3_client,
            cached_results,
            compute_if_no_s3_checksum=compute_if_no_s3_checksum,
        )

        if result_checksum:
            asset_copy.checksum = result_checksum.value
            asset_copy.checksum_alg = result_checksum.algorithm

        result.append(asset_copy)

    return result
