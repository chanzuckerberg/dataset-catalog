import base64
import binascii
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import NamedTuple

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

# The name S3 gives each natively-computed algorithm. One mapping, because the
# same name appears in two shapes: ListObjectsV2 reports it verbatim in
# Contents[].ChecksumAlgorithm, while HeadObject returns the value under
# "Checksum" + name. Deriving the second from the first keeps a listing hint and
# the HEAD that follows it from ever disagreeing about which field to read.
_S3_NATIVE_NAME: dict[Algorithm, str] = {
    Algorithm.crc32: "CRC32",
    Algorithm.crc64nvme: "CRC64NVME",
}

# Maps our algorithm name to the HeadObject response field S3 uses
_S3_NATIVE_RESPONSE_KEY: dict[Algorithm, str] = {
    algo: f"Checksum{name}" for algo, name in _S3_NATIVE_NAME.items()
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


class _ListedObject(NamedTuple):
    """
    One object as ListObjectsV2 described it.

    Every field except the key is `None` when the listing did not supply it,
    which is not the same as supplying an empty or zero value. `algorithms` in
    particular must keep `None` ("this listing does not report checksum
    algorithms") distinct from `frozenset()` ("this object has none"): only the
    second is evidence, and only evidence may cancel a HeadObject. A missing
    size is likewise not 0.
    """

    key: str
    size: int | None
    algorithms: frozenset[str] | None
    checksum_type: str | None
    etag: str | None


@dataclass(frozen=True)
class _FolderSelection:
    """
    The algorithm to hash a prefix with, and the objects it was chosen over.

    `objects` is the single listing pass, handed on so resolution never lists
    the prefix again. It is a materialised list when ranking had to see
    folder-wide totals first, and a lazy iterator when the caller named the
    algorithm — there is nothing to rank then, so resolution can start on the
    first page rather than waiting out pagination.

    Selection deliberately reports no coverage. The listing carries no digest
    values, so how many children are actually reusable is not knowable until
    the resolution phase has run.
    """

    algorithm: Algorithm | None = None
    objects: Iterable[_ListedObject] = ()


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


def _listing_excludes_native(listed: _ListedObject, algorithm: Algorithm) -> bool:
    """
    Whether the listing proves a HeadObject cannot yield `algorithm`.

    Only a positive statement counts. A listing that reports algorithms and
    omits this one — including an explicitly empty list — has ruled it out, and
    so has one reporting it as a multipart COMPOSITE, which is not comparable
    with a whole-object hash. Everything else (no algorithm field at all, or a
    metadata-backed algorithm the listing could never mention) leaves the HEAD
    in place: skipping it on an absent field would silently stop reusing stored
    checksums on any store that does not populate it.

    A multipart ETag is deliberately not consulted. It marks a multipart upload,
    not a composite checksum, and a multipart object may well carry a
    whole-object CRC64NVME. The cost model prices that case pessimistically
    (_listing_suggests_reuse); this one must not act on the same guess.
    """
    name = _S3_NATIVE_NAME.get(algorithm)
    if name is None or listed.algorithms is None:
        return False
    if name not in listed.algorithms:
        return True
    return listed.checksum_type == "COMPOSITE"


def _listing_suggests_reuse(listed: _ListedObject, algorithm: Algorithm) -> bool:
    """
    Whether the listing gives reason to hope this object's `algorithm`
    checksum is reusable — a cost estimate, never a decision.

    Pessimistic where the listing is ambiguous: a reported algorithm with no
    ChecksumType on an object whose ETag carries a multipart suffix is priced
    as a download, because that is the shape a composite checksum takes on a
    listing that omits the type. It may overcharge a multipart object that
    really does hold a whole-object digest, which costs a worse ranking and
    nothing else — the worker still HEADs it and still reuses what it finds.

    The ETag is quoted in the listing ('"abc"-3'), and _has_multipart_suffix
    requires the part count to be the last characters, so the quotes come off
    before the test.
    """
    native_name = _S3_NATIVE_NAME.get(algorithm)
    if (
        native_name is None
        or listed.algorithms is None
        or native_name not in listed.algorithms
    ):
        return False
    if listed.checksum_type is not None:
        return listed.checksum_type != "COMPOSITE"
    return not (
        listed.etag is not None and _has_multipart_suffix(listed.etag.strip('"'))
    )


def _native_candidates(objects: list[_ListedObject]) -> set[Algorithm]:
    """
    The native algorithms worth ranking for a prefix, from the listing alone.

    An algorithm only ever seen on COMPOSITE objects is no candidate: those
    values cannot be compared with a whole-object hash, so reporting them
    would price a folder as covered that in fact needs downloading throughout.

    Intersected with what this install can compute, as before: an algorithm S3
    stored but whose hasher is missing cannot combine children into a folder
    digest, so choosing it would fail partway through the walk.
    """
    reported: set[str] = set()
    for listed in objects:
        if listed.algorithms is None or listed.checksum_type == "COMPOSITE":
            continue
        reported |= listed.algorithms
    return {
        algorithm for algorithm, name in _S3_NATIVE_NAME.items() if name in reported
    } & available_algorithms()


def _cheapest_algorithm(objects: list[_ListedObject]) -> Algorithm:
    """
    The algorithm requiring the least recompute across a prefix's children.

    Coverage does not have to be universal. Every child that already carries
    the chosen algorithm is reused; only the rest are downloaded and hashed.
    Mixing the two is sound because a stored digest and a computed one are the
    same value — see ChecksumResult.content_digest.

    Ranked from the listing, which means only S3-native algorithms can be
    discovered here: a blake3 written into user metadata is invisible until a
    HeadObject reads it, and reading one per object before choosing is the
    round trip this phase exists to avoid. Name such an algorithm explicitly to
    have it reused. The default is the fallback when the listing offers no
    native candidate, not a competitor to one that it does.
    """
    candidates = _native_candidates(objects)
    if not candidates:
        # Nothing reusable in sight: hash every child from scratch. blake2b is
        # stdlib, so default_algorithm() always resolves to something buildable.
        return default_algorithm()

    def rank(algorithm: Algorithm) -> tuple[float, int]:
        missing = [o for o in objects if not _listing_suggests_reuse(o, algorithm)]
        # `or 0`: an unreported size prices as free rather than aborting the
        # ranking. It only has to order the options, and a child whose size the
        # listing withheld still costs its round trip via missing_count.
        cost = _recompute_cost(
            sum(o.size or 0 for o in missing), len(missing), algorithm
        )
        # Priority breaks ties only. A tie means both need the same recompute
        # -- usually none at all -- so nothing is paid for preferring one.
        return cost, -ALGORITHM_PRIORITY.get(algorithm, 0)

    return min(candidates, key=rank)


def _iter_listing(s3_client, bucket: str, prefix: str) -> Iterator[_ListedObject]:
    """
    Yield a _ListedObject for every object under a prefix, skipping folder
    markers.

    The single place the listing rules live, so selection and hashing always see
    the same set of objects. Everything the listing withholds stays None rather
    than being defaulted — see _ListedObject.

    ChecksumAlgorithm arrives as a list, so it becomes a frozenset; the
    membership tests downstream are the only thing that reads it, and a
    hashable value keeps a _ListedObject usable as a dict key.
    """
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("/"):
                continue
            algorithms = obj.get("ChecksumAlgorithm")
            yield _ListedObject(
                key=obj["Key"],
                size=obj.get("Size"),
                algorithms=None if algorithms is None else frozenset(algorithms),
                checksum_type=obj.get("ChecksumType"),
                etag=obj.get("ETag"),
            )


def _select_folder_algorithm(
    path: str,
    s3_client,
    algorithm: Algorithm | None = None,
) -> _FolderSelection:
    """
    Choose the algorithm to hash a prefix with, and hand on its listing.

    Issues no HeadObject and no GetObject: the choice is made from what
    ListObjectsV2 already reports about each object. Whether a given child's
    checksum is genuinely reusable is settled per object during resolution,
    which is where the digest values actually arrive.

    A child with no usable checksum does not discard the rest — it just becomes
    one object to download, while every other child still contributes its
    stored digest.

    `algorithm` names the algorithm outright. Nothing then has to be ranked, so
    the listing is passed on unconsumed and resolution overlaps its own
    requests with pagination. Auto-selection cannot: it ranks over folder-wide
    totals, so every page must be read before the first object is resolved.
    """
    if not path.startswith(("s3://", "s3a://")):
        return _FolderSelection()

    bucket, key = _parse_s3_uri(path)
    # Same normalisation the compute phase applies, so selection and hashing
    # always see the same set of objects.
    listing = _iter_listing(s3_client, bucket, _folder_prefix(key))

    if algorithm is not None:
        # Logged before the listing is consumed, so this line appears even for
        # a prefix whose pagination or resolution then fails — which is when
        # knowing which algorithm was in play matters most.
        logger.debug("Selected %s for %s: requested explicitly", algorithm, path)
        return _FolderSelection(algorithm, listing)

    objects = list(listing)
    chosen = _cheapest_algorithm(objects)
    logger.debug(
        "Selected %s for %s: cheapest over %d listed objects",
        chosen,
        path,
        len(objects),
    )
    return _FolderSelection(chosen, objects)
