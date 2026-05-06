import base64

from catalog_client.utils.checksum.algorithm import Algorithm
from catalog_client.utils.checksum.models import ChecksumResult

# Maps our algorithm name to the HeadObject response field S3 uses
_S3_NATIVE_RESPONSE_KEY: dict[Algorithm, str] = {
    Algorithm.crc32: "ChecksumCRC32",
    Algorithm.crc64nvme: "ChecksumCRC64NVME",
}

_NON_S3_NATIVE_ALGORITHMS: set[Algorithm] = {a for a in Algorithm if a not in _S3_NATIVE_RESPONSE_KEY}

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


def _select_best_algorithm(algorithms: set[Algorithm]) -> Algorithm | None:
    """Select the highest-priority algorithm from a set of algorithm names."""
    if not algorithms:
        return None
    return max(algorithms, key=lambda a: ALGORITHM_PRIORITY.get(a, 0))


def _b64_to_hex(b64: str) -> str:
    """Convert a base64 checksum string (as returned by S3) to lowercase hex."""
    return base64.b64decode(b64).hex()


def _strip_multipart_suffix(value: str) -> str:
    """
    S3 returns composite checksums as '{base64}-{num_parts}' for multipart
    objects (e.g. 'abc123==-23'). Strip the trailing '-N' if present so we
    get a clean base64 value we can decode.
    """
    if "-" in value:
        b64_part, _, _ = value.rpartition("-")
        return b64_part
    return value


def _fetch_all_s3_stored_checksums(bucket: str, key: str, s3_client) -> dict[Algorithm, ChecksumResult]:
    """
    Fetch all stored checksums for an S3 object in one HeadObject call.
    Returns dict mapping algorithm -> ChecksumResult.
    Returns empty dict on any error.
    """
    results: dict[Algorithm, ChecksumResult] = {}
    path = f"s3://{bucket}/{key}"

    try:
        head = s3_client.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")

        # Native S3 checksums (CRC32, CRC64NVME)
        for algo, response_key in _S3_NATIVE_RESPONSE_KEY.items():
            if raw_value := head.get(response_key):
                clean_b64 = _strip_multipart_suffix(raw_value)
                hex_digest = _b64_to_hex(clean_b64)
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
            if file_hash:
                merkle_root = metadata.get(f"x-checksum-{algo}-merkle", file_hash)
                results[algo] = ChecksumResult(
                    path=path,
                    algorithm=algo,
                    file_hash=file_hash,
                    merkle_root=merkle_root,
                    source="s3_metadata",
                )

    except Exception:
        return {}

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


def _find_common_algorithm_in_folder(path: str, s3_client) -> tuple[str | None, dict[str, ChecksumResult]]:
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

    bucket, prefix = _parse_s3_uri(path)
    common_algorithms: set[Algorithm] | None = None
    per_child_all_checksums: dict[str, dict[Algorithm, ChecksumResult]] = {}

    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("/"):
                continue

            child_path = f"s3://{bucket}/{obj['Key']}"
            all_checksums = _fetch_all_s3_stored_checksums(bucket, obj["Key"], s3_client)

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
    return best_algorithm, {p: results[best_algorithm] for p, results in per_child_all_checksums.items()}
