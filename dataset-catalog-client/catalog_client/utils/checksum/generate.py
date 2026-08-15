import logging
import warnings
from dataclasses import dataclass
from typing import TypeVar

from catalog_client.models.asset import AssetType, DataAssetRequest, StoragePlatform
from catalog_client.utils.checksum._parallel import owned_s3_client
from catalog_client.utils.checksum.algorithm import Algorithm, default_algorithm
from catalog_client.utils.checksum.hashing import (
    compute_checksum_localfs,
    compute_checksum_s3,
)
from catalog_client.utils.checksum.models import ChecksumResult, LocationChecksum
from catalog_client.utils.checksum.s3 import (
    _fetch_all_s3_stored_checksums,
    _parse_s3_uri,
    _select_best_algorithm,
    _select_folder_algorithm,
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
    needs both fields to route correctly; dropping one silently changes
    behaviour (see `covers_all_children`, whose predecessor defaulted to False
    on the auto-detect path and made algorithm=None strictly worse than
    naming the algorithm auto-detection would have chosen).

    covers_all_children is a boolean rather than the child counts it is derived
    from: only this answer has a reader, and carrying the counts obliged the
    single-object branches to invent a total of 1 to make the arithmetic agree.
    _FolderSelection still reports the counts, which is where they are real.
    """

    algorithm: Algorithm | None
    covers_all_children: bool = False


def detect_and_cache_for_s3(
    location_uri: str,
    asset_type: AssetType,
    algorithm: Algorithm | None,
    cached_results: dict[str, ChecksumResult],
    s3_client,
    max_workers: int | None = None,
) -> _S3Detection:
    if asset_type == AssetType.folder:
        # Every child carrying the chosen algorithm is reusable, whether that
        # algorithm was named by the caller or picked here by cost. Coverage
        # need not be universal: a child without it is one download, not a
        # reason to discard the digests every other child already has.
        selection = _select_folder_algorithm(
            location_uri, s3_client, algorithm, max_workers
        )
        if selection.algorithm is None:
            return _S3Detection(algorithm=None)
        cached_results.update(selection.cached)
        return _S3Detection(selection.algorithm, selection.covers_all_children)

    bucket, key = _parse_s3_uri(location_uri)
    all_checksums = _fetch_all_s3_stored_checksums(bucket, key, s3_client)
    # A named algorithm is used as named; otherwise pick the best one stored.
    # Not intersected with available_algorithms(): a stored digest is returned
    # as-is and never re-hashed, so an uninstalled hasher is no obstacle here —
    # unlike the folder path, which must combine children.
    chosen = (
        algorithm
        if algorithm is not None
        else _select_best_algorithm(set(all_checksums))
    )
    # A single object is either covered or not, which is all the compute phase
    # asks; there are no children to count.
    if chosen is not None and chosen in all_checksums:
        cached_results[location_uri] = all_checksums[chosen]
        return _S3Detection(chosen, covers_all_children=True)
    return _S3Detection(chosen)


def compute_for_s3(
    location_uri: str,
    asset_type: AssetType,
    algorithm: Algorithm | None,
    cached_results: dict[str, ChecksumResult],
    s3_client,
    compute_if_no_s3_checksum: bool,
    max_workers: int | None = None,
) -> ChecksumResult | None:
    detection = detect_and_cache_for_s3(
        location_uri, asset_type, algorithm, cached_results, s3_client, max_workers
    )
    if detection.algorithm and location_uri in cached_results:
        return cached_results[location_uri]

    # Assembling a folder digest from already-cached children needs no
    # downloads, so compute_if_no_s3_checksum does not apply to it. Partial
    # coverage does not qualify: the children that are missing would still
    # have to be fetched, which is exactly what this flag forbids.
    if not compute_if_no_s3_checksum and not detection.covers_all_children:
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
        max_workers=max_workers,
    )


def for_location(
    location_uri: str,
    asset_type: AssetType,
    storage_platform: StoragePlatform | None = None,
    algorithm: Algorithm | None = None,
    s3_client=None,
    cached_results: dict[str, ChecksumResult] | None = None,
    compute_if_no_s3_checksum: bool = True,
    max_workers: int | None = None,
) -> LocationChecksum:
    """
    Compute the checksum for a single location.

    Returns an empty (falsy) LocationChecksum when the location is skipped or
    fails; every such case also emits a ChecksumWarning, so a caller can turn
    all of them into errors with
    `warnings.simplefilter("error", ChecksumWarning)`.

    max_workers caps the threads used for a folder; None picks a default and 1
    forces serial. It never affects the digest. Warnings are always raised on
    the calling thread, so the ChecksumWarning contract above holds either way.
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
                max_workers,
            )
        else:
            hash_result = compute_checksum_localfs(
                location_uri,
                algorithm=algorithm or default_algorithm(),
                max_workers=max_workers,
            )

        if hash_result is not None:
            # content_digest, not merkle_root — the same value this node would
            # contribute to a parent directory. See ChecksumResult.content_digest.
            return LocationChecksum(
                value=hash_result.content_digest,
                algorithm=hash_result.algorithm,
                total_size=hash_result.total_size,
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
    max_workers: int | None = None,
) -> list[AssetT]:
    """
    Return copies of the given assets with `checksum`, `checksum_alg` and
    `size_bytes` populated.

    The input assets are NOT modified: each is shallow-copied via
    `model_copy()`, preserving its concrete type, and the copies are returned.
    Read the results off the returned list.

    `size_bytes` is read from storage-platform metadata (os.stat, S3
    ContentLength, S3 listing sizes), so it costs no extra I/O and is set even
    when a stored S3 checksum avoids downloading the object. It is only written
    on assets where it is None, and only where a checksum was produced.

    algorithm=None auto-detects from stored S3 checksums (highest priority wins),
    falling back to `default_algorithm()` if none exist. Non-S3 assets always
    compute locally.

    compute_if_no_s3_checksum=False skips S3 assets that have no stored checksum
    rather than downloading them. It does not apply to folders whose children
    all carry a stored checksum, since assembling those needs no download, nor
    to non-S3 assets.

    Unsupported platforms (external, other, None) are passed through with a
    ChecksumWarning. Failures also warn and pass the asset through unchanged.

    max_workers caps the threads used within each folder; None picks a default
    and 1 forces serial. Assets themselves are always processed one at a time,
    so every ChecksumWarning is raised on the calling thread. It never affects
    a digest. A client passed in here is used as-is, including its connection
    pool limit, which the S3 worker count is clamped to.
    """
    if not assets:
        return []

    result: list[AssetT] = []
    cached_results: dict[str, ChecksumResult] = {}
    if s3_client is None:
        # Ours to configure, so the pool is sized for the workers the folder
        # scan will ask for rather than left at botocore's default 10.
        s3_client = owned_s3_client(max_workers)

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
            max_workers=max_workers,
        )

        if result_checksum:
            asset_copy.checksum = result_checksum.value
            asset_copy.checksum_alg = result_checksum.algorithm
            # A size the caller already supplied wins: they may be describing
            # something we cannot see (a logical size, a pre-move total), and
            # silently replacing it would be a surprise mutation.
            if asset_copy.size_bytes is None and result_checksum.total_size is not None:
                asset_copy.size_bytes = result_checksum.total_size

        result.append(asset_copy)

    return result
