import base64
import binascii
import logging

from catalog_client.utils.checksum.algorithm import Algorithm, is_valid_digest
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

# Algorithm priority for selection (higher = preferred, computed over native)
ALGORITHM_PRIORITY: dict[Algorithm, int] = {
    Algorithm.blake3: 100,
    Algorithm.blake2b: 90,
    Algorithm.crc64: 80,
    Algorithm.crc64nvme: 70,
    Algorithm.crc32: 60,
}


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


def _find_common_algorithm_in_folder(
    path: str, s3_client
) -> tuple[Algorithm | None, dict[str, ChecksumResult]]:
    """
    Find the best common algorithm across all files under a folder.

    Returns:
        (algorithm, child_checksums)
        - algorithm: highest-priority algorithm shared by ALL children,
                     or None if no common algorithm exists.
        - child_checksums: dict mapping child_path -> ChecksumResult for the
                           chosen algorithm. Empty if no common algorithm found.
    """
    if not path.startswith(("s3://", "s3a://")):
        return None, {}

    bucket, key = _parse_s3_uri(path)
    # Same normalisation the compute phase applies, so detection and hashing
    # always see the same set of objects.
    prefix = _folder_prefix(key)
    common_algorithms: set[Algorithm] | None = None
    per_child_all_checksums: dict[str, dict[Algorithm, ChecksumResult]] = {}

    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("/"):
                continue

            child_path = f"s3://{bucket}/{obj['Key']}"
            all_checksums = _fetch_all_s3_stored_checksums(
                bucket, obj["Key"], s3_client
            )

            if not all_checksums:
                return None, {}

            child_algos = set(all_checksums.keys())

            if common_algorithms is None:
                common_algorithms = child_algos
            else:
                common_algorithms &= child_algos

            if not common_algorithms:
                return None, {}

            per_child_all_checksums[child_path] = all_checksums

    if not common_algorithms:
        return None, {}

    best_algorithm = _select_best_algorithm(common_algorithms)
    if best_algorithm is None:
        return None, {}
    return best_algorithm, {
        p: results[best_algorithm] for p, results in per_child_all_checksums.items()
    }
