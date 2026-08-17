import base64
import binascii
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

from catalog_client.utils.checksum._parallel import ordered_map, s3_workers
from catalog_client.utils.checksum.algorithm import (
    HASH_THROUGHPUT_MB_S,
    Algorithm,
    available_algorithms,
    default_algorithm,
    is_valid_digest,
)
from catalog_client.utils.checksum.models import ChecksumResult

logger = logging.getLogger(__name__)

# HeadObject error codes that genuinely mean "this object has no stored
# checksum because it does not exist". Anything else (403, throttling,
# expired credentials) must not be silently reported as "no checksum".
_MISSING_OBJECT_ERROR_CODES = frozenset({"404", "NoSuchKey", "NotFound"})

# Maps our algorithm name to the HeadObject response field S3 uses
_S3_NATIVE_RESPONSE_KEY: dict[Algorithm, str] = {
    Algorithm.crc32: "ChecksumCRC32",
    Algorithm.crc64nvme: "ChecksumCRC64NVME",
}

_NON_S3_NATIVE_ALGORITHMS: set[Algorithm] = {
    a for a in Algorithm if a not in _S3_NATIVE_RESPONSE_KEY
}

# Preference order among algorithms (higher wins). S3-native first: those are
# the values S3 computes and can verify itself, so reusing one keeps a catalog
# digest comparable with what the platform reports, and they are also the
# fastest to recompute when a child is missing one.
#
# For folders this only breaks ties in _cheapest_algorithm — a tie means both
# options need the same recompute, usually none, so preferring one costs
# nothing. For single files it is the whole selection.
#
# crc64 ranks last deliberately: it is ~90x slower than crc64nvme for the same
# 64-bit width, needs a third-party package, and is the one algorithm here
# whose extension never releases the GIL, so it cannot be parallelised either.
ALGORITHM_PRIORITY: dict[Algorithm, int] = {
    Algorithm.crc64nvme: 100,
    Algorithm.crc32: 90,
    Algorithm.blake3: 80,
    Algorithm.blake2b: 70,
    Algorithm.crc64: 60,
}

# Weights for ranking folder algorithms by how much recompute each would cost.
# Deliberately coarse: they only have to order the options, not predict a
# duration, and the caller's real bandwidth is unknowable from here.
#
# _REQUEST_BYTE_EQUIVALENT is what makes the ranking sensitive to file *count*
# and not only to bytes. A folder of a hundred thousand tiny objects is
# dominated by round trips, so an algorithm covering more objects can win even
# when it covers fewer bytes.
_REQUEST_BYTE_EQUIVALENT = 4 * 1024 * 1024
_NETWORK_MB_S = 100.0


@dataclass(frozen=True)
class _FolderSelection:
    """
    The algorithm to hash a prefix with, and the children already carrying it.

    total_children is the count the prefix listing found, so a caller can tell
    complete coverage (assembling the folder digest needs no downloads) from
    partial coverage (some children must be fetched), which is the distinction
    compute_if_no_s3_checksum turns on.
    """

    algorithm: Algorithm | None = None
    cached: dict[str, ChecksumResult] = field(default_factory=dict)
    total_children: int = 0

    @property
    def covers_all_children(self) -> bool:
        """
        Whether the folder digest can be assembled without downloading anything.

        Lives here, next to the two values it compares, so the rule is stated
        once. Partial coverage is still useful — it saves a download per cached
        child — but it is not the same as complete coverage, and only complete
        coverage may proceed under compute_if_no_s3_checksum=False.
        """
        return self.total_children > 0 and len(self.cached) == self.total_children


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Parse s3:// or s3a:// URI into (bucket, key)."""
    for scheme in ("s3://", "s3a://"):
        if uri.startswith(scheme):
            without_scheme = uri[len(scheme) :]
            bucket, _, key = without_scheme.partition("/")
            return bucket, key
    raise ValueError(f"Not an S3 URI: {uri}")


def _folder_prefix(key: str) -> str:
    """
    Normalise an S3 key into a folder prefix.

    A prefix without a trailing slash over-matches siblings: listing "ds"
    also returns objects under "ds2/". Appending the slash confines the
    listing to the intended folder. An empty key (bucket root) is returned
    unchanged.
    """
    if not key or key.endswith("/"):
        return key
    return f"{key}/"


def _is_folder_key(key: str) -> bool:
    """
    Whether an S3 key names a prefix rather than a single object.

    A trailing slash means prefix, and so does an empty key — that is the bucket
    root, which cannot be an object. The one statement of the rule, so an entry
    point that infers the asset type cannot drift from the one that consumes it.
    """
    return not key or key.endswith("/")


def _is_folder_uri(uri: str) -> bool:
    """`_is_folder_key` for callers holding a whole URI rather than a key."""
    return _is_folder_key(_parse_s3_uri(uri)[1])


def _insert_key(tree: dict, parts: list[str], s3_key: str) -> None:
    """
    Insert an S3 key into a nested dict keyed by path segment.

    Leaves are ("file", s3_key) tuples; interior nodes are dicts. Lets a flat
    list_objects_v2 listing be walked as a virtual directory tree.
    """
    if len(parts) == 1:
        tree[parts[0]] = ("file", s3_key)
    else:
        tree.setdefault(parts[0], {})
        _insert_key(tree[parts[0]], parts[1:], s3_key)


def _select_best_algorithm(algorithms: set[Algorithm]) -> Algorithm | None:
    """Select the highest-priority algorithm from a set of algorithm names."""
    if not algorithms:
        return None
    return max(algorithms, key=lambda a: ALGORITHM_PRIORITY.get(a, 0))


def _b64_to_hex(b64: str) -> str:
    """Convert a base64 checksum string (as returned by S3) to lowercase hex."""
    return base64.b64decode(b64).hex()


def _has_multipart_suffix(value: str) -> bool:
    """
    S3 returns composite checksums as '{base64}-{num_parts}' for multipart
    objects (e.g. 'abc123==-23'). The standard base64 alphabet has no '-',
    so a trailing '-N' unambiguously marks a composite value.
    """
    head, sep, tail = value.rpartition("-")
    return bool(sep) and tail.isdigit()


def _is_composite(head: dict, raw_value: str) -> bool:
    """
    Decide whether a native checksum value covers the whole object or is a
    multipart composite (a checksum computed over the part checksums).

    A composite value cannot be compared against a checksum computed over the
    object's bytes: it depends on the uploader's part size, which we neither
    know nor reproduce. Prefer the explicit ChecksumType field and fall back
    to the '-N' suffix for responses that omit it.
    """
    checksum_type = head.get("ChecksumType")
    if checksum_type:
        return checksum_type == "COMPOSITE"
    return _has_multipart_suffix(raw_value)


def _missing_object_error_code(exc: Exception) -> str | None:
    """
    Return the S3 error code if exc is a botocore ClientError, else None.

    Read off the exception duck-typed rather than importing botocore, so that
    `import catalog_client` does not pull in boto3's several hundred modules
    (see the lazy import in generate.for_assets).
    """
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    return response.get("Error", {}).get("Code")


def _fetch_all_s3_stored_checksums(
    bucket: str, key: str, s3_client
) -> dict[Algorithm, ChecksumResult]:
    """
    Fetch all stored checksums for an S3 object in one HeadObject call.
    Returns dict mapping algorithm -> ChecksumResult.

    Returns an empty dict when the object does not exist. Any other error
    (403, throttling, expired credentials) is re-raised so the caller can
    surface it, rather than being silently reported as "no stored checksum" —
    which would trigger a needless full download or a silent skip.

    Multipart composite checksums are excluded: they are not comparable with
    a checksum computed over the object's bytes.
    """
    results: dict[Algorithm, ChecksumResult] = {}
    path = f"s3://{bucket}/{key}"

    try:
        head = s3_client.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
    except Exception as exc:
        if _missing_object_error_code(exc) in _MISSING_OBJECT_ERROR_CODES:
            logger.debug("No S3 object at %s; treating as no stored checksum", path)
            return {}
        raise

    # The size rides along on the response we already made, so a stored
    # checksum reports a size without ever reading the object's bytes.
    content_length = head.get("ContentLength")

    # Native S3 checksums (CRC32, CRC64NVME)
    for algo, response_key in _S3_NATIVE_RESPONSE_KEY.items():
        raw_value = head.get(response_key)
        if not isinstance(raw_value, str) or not raw_value:
            continue
        if _is_composite(head, raw_value):
            logger.debug(
                "Ignoring composite %s checksum on %s: not comparable with a "
                "whole-object hash",
                algo,
                path,
            )
            continue
        # One unreadable value must not discard the object's other checksums,
        # so decoding failures skip just this algorithm.
        try:
            hex_digest = _b64_to_hex(raw_value)
        except (ValueError, binascii.Error):
            logger.debug("Ignoring undecodable %s checksum on %s", algo, path)
            continue
        if not is_valid_digest(hex_digest, algo):
            logger.debug("Ignoring malformed %s checksum on %s", algo, path)
            continue
        results[algo] = ChecksumResult(
            path=path,
            algorithm=algo,
            file_hash=hex_digest,
            merkle_root=hex_digest,
            total_size=content_length,
            source="s3_native",
        )

    # User metadata checksums (blake3, blake2b, crc64)
    metadata = {k.lower(): v for k, v in head.get("Metadata", {}).items()}
    for algo in _NON_S3_NATIVE_ALGORITHMS:
        file_hash = metadata.get(f"x-checksum-{algo}")
        if not file_hash:
            continue
        if not is_valid_digest(file_hash, algo):
            # Not a digest we could combine into a folder root, so refusing it
            # here keeps a file's checksum identical standalone and as a child.
            logger.debug("Ignoring malformed x-checksum-%s metadata on %s", algo, path)
            continue
        merkle_root = metadata.get(f"x-checksum-{algo}-merkle", file_hash)
        results[algo] = ChecksumResult(
            path=path,
            algorithm=algo,
            file_hash=file_hash,
            merkle_root=merkle_root,
            total_size=content_length,
            source="s3_metadata",
        )

    return results


def _fetch_s3_stored_checksum(
    bucket: str,
    key: str,
    algorithm: Algorithm,
    s3,
) -> ChecksumResult | None:
    """
    Attempt to retrieve a stored checksum from S3 without downloading the object.
    Returns None if no stored checksum is found for the requested algorithm.
    """
    return _fetch_all_s3_stored_checksums(bucket, key, s3).get(algorithm)


def _recompute_cost(
    missing_bytes: int, missing_count: int, algorithm: Algorithm
) -> float:
    """Rough seconds to fetch and hash the children that lack `algorithm`."""
    effective_mb = (
        missing_bytes + missing_count * _REQUEST_BYTE_EQUIVALENT
    ) / 1_048_576
    return effective_mb * (1.0 / _NETWORK_MB_S + 1.0 / HASH_THROUGHPUT_MB_S[algorithm])


def _cheapest_algorithm(
    per_child: dict[str, dict[Algorithm, ChecksumResult]],
    sizes: dict[str, int | None],
) -> Algorithm:
    """
    The algorithm requiring the least recompute across a prefix's children.

    Coverage does not have to be universal. Every child that already carries
    the chosen algorithm is reused; only the rest are downloaded and hashed.
    Mixing the two is sound because a stored digest and a computed one are the
    same value — see ChecksumResult.content_digest.

    Candidates are intersected with what this install can compute: an algorithm
    S3 stored but whose hasher is missing cannot combine children into a folder
    digest, so choosing it would fail partway through the walk.
    """
    candidates = {
        algorithm for results in per_child.values() for algorithm in results
    } & available_algorithms()
    # Always an option, and the answer when nothing has a stored checksum:
    # hash every child from scratch. blake2b is stdlib, so this is never empty.
    candidates.add(default_algorithm())

    def rank(algorithm: Algorithm) -> tuple[float, int]:
        missing = [child for child, r in per_child.items() if algorithm not in r]
        # `or 0`: an unreported size prices as free rather than aborting the
        # ranking. It only has to order the options, and a child whose size the
        # listing withheld still costs its round trip via missing_count.
        cost = _recompute_cost(
            sum(sizes.get(child) or 0 for child in missing), len(missing), algorithm
        )
        # Priority breaks ties only. A tie means both need the same recompute
        # -- usually none at all -- so nothing is paid for preferring one.
        return cost, -ALGORITHM_PRIORITY.get(algorithm, 0)

    return min(candidates, key=rank)


def _iter_listing(
    s3_client, bucket: str, prefix: str
) -> Iterator[tuple[str, int | None]]:
    """
    Yield (key, size) for every object under a prefix, skipping folder markers.

    The single place the listing rules live, so detection and hashing always see
    the same set of objects. Size stays None when the listing does not report
    one: a folder total must distinguish "unknown" from 0, and callers that only
    need a number for arithmetic coerce it themselves.
    """
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("/"):
                continue
            yield obj["Key"], obj.get("Size")


def _select_folder_algorithm(
    path: str,
    s3_client,
    algorithm: Algorithm | None = None,
    max_workers: int | None = None,
) -> _FolderSelection:
    """
    Choose the algorithm to hash a prefix with, and collect reusable children.

    Scans every child once. Unlike a "common algorithm" rule, a child with no
    stored checksum does not discard the rest: it just becomes one object to
    download, while every other child still contributes its stored digest.
    Requiring universality meant a single checksumless object in a 100k-object
    prefix forced 100k downloads.

    `algorithm` names the algorithm outright and skips selection; the scan
    still runs, because it is what finds the children that already carry it.

    For a prefix whose children all carry a stored checksum this scan is the
    entire operation — no object is ever read — so its HeadObjects are issued
    concurrently. Results are consumed in listing order, which keeps an error
    on one child reported the same way a serial loop reported it.
    """
    if not path.startswith(("s3://", "s3a://")):
        return _FolderSelection()

    bucket, key = _parse_s3_uri(path)
    # Same normalisation the compute phase applies, so detection and hashing
    # always see the same set of objects.
    prefix = _folder_prefix(key)

    def head(
        item: tuple[str, int | None],
    ) -> tuple[str, int | None, dict[Algorithm, ChecksumResult]]:
        child_key, size = item
        return (
            child_key,
            size,
            _fetch_all_s3_stored_checksums(bucket, child_key, s3_client),
        )

    # Both maps are keyed by S3 key, not by s3:// path: the full paths are only
    # needed for the children that survive selection, so building them for every
    # object would retain an N-entry string map to discard most of it.
    #
    # Size comes off the listing, which reports it for every object including the
    # ones with no stored checksum at all -- those are exactly the ones the cost
    # model needs to price.
    sizes: dict[str, int | None] = {}
    per_child: dict[str, dict[Algorithm, ChecksumResult]] = {}

    # The listing is consumed lazily through ordered_map's window, so no matter
    # how large the prefix is only a bounded number of futures exist at once.
    # The accumulators below are still O(objects); it is the scheduling state,
    # not the result set, that the window bounds.
    for child_key, size, stored in ordered_map(
        head,
        _iter_listing(s3_client, bucket, prefix),
        s3_workers(s3_client, max_workers),
    ):
        sizes[child_key] = size
        per_child[child_key] = stored

    if not per_child:
        # An empty or non-existent prefix. Pass an explicitly named algorithm
        # through unchanged; there is nothing to detect one from.
        return _FolderSelection(algorithm=algorithm)

    chosen = (
        algorithm if algorithm is not None else _cheapest_algorithm(per_child, sizes)
    )
    cached = {
        f"s3://{bucket}/{child}": r[chosen]
        for child, r in per_child.items()
        if chosen in r
    }
    logger.debug(
        "Selected %s for %s: %d of %d children already carry it",
        chosen,
        path,
        len(cached),
        len(per_child),
    )
    return _FolderSelection(chosen, cached, len(per_child))
