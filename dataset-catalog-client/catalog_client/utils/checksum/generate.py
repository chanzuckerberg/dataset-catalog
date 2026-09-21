import logging
import warnings
from typing import TypeVar

from catalog_client.models.asset import AssetType, DataAssetRequest, StoragePlatform
from catalog_client.utils.checksum._parallel import owned_s3_client
from catalog_client.utils.checksum.algorithm import Algorithm, default_algorithm
from catalog_client.utils.checksum.hashing import (
    _fold_s3_children,
    _hash_s3_file,
    _resolve_s3_objects,
    compute_checksum_localfs,
)
from catalog_client.utils.checksum.models import ChecksumResult, LocationChecksum
from catalog_client.utils.checksum.s3 import (
    _fetch_all_s3_stored_checksums,
    _folder_prefix,
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


def _detect_s3_object(
    location_uri: str,
    algorithm: Algorithm | None,
    s3_client,
) -> tuple[Algorithm | None, ChecksumResult | None]:
    """
    HEAD one S3 object and return the algorithm to use and any digest it
    already carries.

    The second element is None when the chosen algorithm is not stored on the
    object, which is how the caller tells "already covered" from "must be
    computed".
    """
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
    return chosen, all_checksums.get(chosen) if chosen is not None else None


def _compute_folder_for_s3(
    location_uri: str,
    algorithm: Algorithm | None,
    cached_results: dict[str, ChecksumResult],
    s3_client,
    compute_if_no_s3_checksum: bool,
    hash_max_workers: int | None,
    s3_workers: int | None = None,
) -> ChecksumResult | None:
    """
    Discover, select, resolve and fold a prefix in one pass.

    One ListObjectsV2 pagination, one algorithm, one resolution attempt per
    object.

    Coverage is read off the resolved children, never off the listing: the
    listing's checksum hints are a cost estimate and can be both optimistic
    (a reported algorithm whose stored value turns out to be unusable) and
    pessimistic (a multipart ETag over a perfectly good whole-object digest).
    Only what came back may decide whether a digest is reported.
    """
    selection = _select_folder_algorithm(location_uri, s3_client, algorithm)
    bucket, key = _parse_s3_uri(location_uri)
    prefix = _folder_prefix(key)
    chosen = selection.algorithm or default_algorithm()

    # cached_results is the caller's shared dict, written to below but never
    # read here: an entry an earlier asset left behind was validated against
    # that asset's object, not this one. Resolution re-validates every child.
    resolution = _resolve_s3_objects(
        bucket,
        chosen,
        s3_client,
        selection.objects,
        use_stored=True,
        cached_results=None,
        download=compute_if_no_s3_checksum,
        hash_max_workers=hash_max_workers,
        s3_workers=s3_workers,
    )
    # Accumulated even when the folder is then skipped: the digests are real
    # and the caller's cache is the only place they survive the call. Only
    # digests that came off S3 qualify — a computed one was never validated
    # against anything.
    cached_results.update(
        {
            f"s3://{bucket}/{key}": r
            for key, r in resolution.children.items()
            if r.source != "computed"
        }
    )

    # With downloads allowed, resolution leaves nothing unresolved, so this is
    # reached only under compute_if_no_s3_checksum=False. Guarding on the flag
    # rather than on `complete` alone matters for the empty prefix, which is
    # never "complete" but still folds to an empty-folder digest when
    # downloading is permitted — as it did before.
    if not compute_if_no_s3_checksum and not resolution.complete:
        logger.debug(
            "Skipping %s: not every child has a stored S3 checksum and "
            "compute_if_no_s3_checksum=False",
            location_uri,
        )
        return None

    return _fold_s3_children(bucket, prefix, resolution.children, chosen)


def compute_for_s3(
    location_uri: str,
    asset_type: AssetType,
    algorithm: Algorithm | None,
    cached_results: dict[str, ChecksumResult],
    s3_client,
    compute_if_no_s3_checksum: bool,
    hash_max_workers: int | None = None,
    s3_workers: int | None = None,
) -> ChecksumResult | None:
    if asset_type == AssetType.folder:
        return _compute_folder_for_s3(
            location_uri,
            algorithm,
            cached_results,
            s3_client,
            compute_if_no_s3_checksum,
            hash_max_workers,
            s3_workers,
        )

    detected, stored = _detect_s3_object(location_uri, algorithm, s3_client)
    if stored is not None:
        cached_results[location_uri] = stored
    # The effective algorithm, not the detected one: a HEAD that found nothing
    # leaves that None and the default takes over below, so logging the raw
    # detection would name an algorithm no digest was ever produced under.
    chosen = detected or default_algorithm()
    logger.debug("Selected %s for %s", chosen, location_uri)

    if stored is not None:
        return stored

    if not compute_if_no_s3_checksum:
        logger.debug(
            "Skipping %s: no stored S3 checksum and compute_if_no_s3_checksum=False",
            location_uri,
        )
        return None

    # Detection already consulted both the stored metadata and the cache, so
    # they are switched off here to avoid a second HeadObject for this object.
    bucket, key = _parse_s3_uri(location_uri)
    return _hash_s3_file(
        bucket,
        key,
        algorithm=chosen,
        s3=s3_client,
        use_stored=False,
        cached_results=None,
    )


def for_location(
    location_uri: str,
    asset_type: AssetType,
    storage_platform: StoragePlatform | None = None,
    algorithm: Algorithm | None = None,
    s3_client=None,
    cached_results: dict[str, ChecksumResult] | None = None,
    compute_if_no_s3_checksum: bool = True,
    hash_max_workers: int | None = None,
    s3_workers: int | None = None,
) -> LocationChecksum:
    """
    Compute the checksum for a single location.

    Returns an empty (falsy) LocationChecksum when the location is skipped or
    fails; every such case also emits a ChecksumWarning, so a caller can turn
    all of them into errors with
    `warnings.simplefilter("error", ChecksumWarning)`.

    hash_max_workers caps the threads used to hash file content and s3_workers
    the concurrent S3 requests, the latter winning on an S3 folder and ignored
    for a local path. None picks a default and 1 forces serial; neither affects
    the digest. Warnings are always raised on the calling thread, so the
    ChecksumWarning contract above holds either way.
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
                hash_max_workers,
                s3_workers,
            )
        else:
            hash_result = compute_checksum_localfs(
                location_uri,
                algorithm=algorithm or default_algorithm(),
                hash_max_workers=hash_max_workers,
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
    hash_max_workers: int | None = None,
    s3_workers: int | None = None,
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

    hash_max_workers caps the threads used to hash file content within each
    folder and s3_workers the concurrent S3 requests, the latter winning on an
    S3 folder. None picks a default and 1 forces serial. Assets themselves are
    always processed one at a time, so every ChecksumWarning is raised on the
    calling thread. Neither affects a digest. A client passed in here is used
    as-is, including its connection pool limit, which the S3 worker count is
    clamped to.
    """
    if not assets:
        return []

    result: list[AssetT] = []
    cached_results: dict[str, ChecksumResult] = {}
    owned_client = None

    try:
        for asset in assets:
            asset_copy = asset.model_copy()
            if asset_copy.checksum is not None:
                result.append(asset_copy)
                continue

            if (
                s3_client is None
                and asset_copy.storage_platform == StoragePlatform.s3
                and asset_copy.location_uri
            ):
                owned_client = s3_client = owned_s3_client(s3_workers, hash_max_workers)

            result_checksum = for_location(
                asset_copy.location_uri,
                asset_copy.asset_type,
                asset_copy.storage_platform,
                algorithm,
                s3_client,
                cached_results,
                compute_if_no_s3_checksum=compute_if_no_s3_checksum,
                hash_max_workers=hash_max_workers,
                s3_workers=s3_workers,
            )

            if result_checksum:
                asset_copy.checksum = result_checksum.value
                asset_copy.checksum_alg = result_checksum.algorithm
                # A size the caller already supplied wins: they may be describing
                # something we cannot see (a logical size, a pre-move total), and
                # silently replacing it would be a surprise mutation.
                if (
                    asset_copy.size_bytes is None
                    and result_checksum.total_size is not None
                ):
                    asset_copy.size_bytes = result_checksum.total_size

            result.append(asset_copy)

    finally:
        if owned_client is not None:
            owned_client.close()

    return result
