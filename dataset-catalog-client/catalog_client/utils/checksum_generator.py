"""
Checksum utility — BLAKE3, BLAKE2b, CRC32, CRC64 (ECMA-182), CRC64NVME.
Supports local filesystem and S3.

Dependencies:
    pip install blake3 boto3 crcmod awscrt

    awscrt is only required for crc64nvme. All other algorithms work without it.

Algorithm notes:
    blake3 / blake2b  — cryptographic hashes; combine chunks via Merkle tree.
    crc32             — zlib (stdlib); uses S3-style composite for multi-chunk.
    crc64             — CRC64/ECMA-182 via crcmod; S3-style composite.
    crc64nvme         — AWS NVMe CRC64 via awscrt; natively verified by S3.

    S3 natively supports CRC32, CRC32C, CRC64NVME as checksum algorithms
    (set on upload, verified server-side). BLAKE3/BLAKE2b are client-side only.

    For S3 uploads use result.s3_base64 — S3 expects base64-encoded checksums,
    not hex.

Usage:
    # Local file
    result = checksum("data/file.h5ad", algorithm="blake3")

    # Local folder
    result = checksum("data/dataset/", algorithm="crc64nvme")

    # S3 file
    result = checksum("s3://my-bucket/path/to/file.h5ad", algorithm="crc32")

    # S3 folder (prefix)
    result = checksum("s3://my-bucket/path/to/dataset/", algorithm="blake3")
"""

import base64
import io
import os
import struct

import boto3

from catalog_client.utils.checksum.algorithms import (
    Algorithm,
    hash_bytes_independent,
    new_hasher,
)
from catalog_client.utils.checksum.models import (
    CHUNK_SIZE,
    ChecksumResult,
    ChunkRecord,
)

READ_BUFFER = 64 * 1024  # 64KB  I/O buffer


def _iter_stream(stream):
    """Yield READ_BUFFER-sized chunks from any file-like object."""
    while True:
        chunk = stream.read(READ_BUFFER)
        if not chunk:
            break
        yield chunk


def _combine_child_digests(raw_digests: list[bytes], algorithm: Algorithm) -> str:
    """
    Combine child raw digests into a single parent digest.

    Crypto (blake3, blake2b):
        Feeds concatenated raw child hashes into a new hasher — Merkle node.

    CRC (crc32, crc64, crc64nvme):
        Computes CRC over the concatenated raw child CRC bytes — matches S3's
        composite checksum model for multipart uploads.

    Both cases use the same operation: hash/CRC of concatenated raw bytes.
    The difference is only in what "raw bytes" means per algorithm type:
    - crypto  → raw bytes of the hex digest
    - crc32   → 4 big-endian bytes of the CRC integer
    - crc64*  → 8 big-endian bytes of the CRC integer
    """
    combined = b"".join(raw_digests)
    return hash_bytes_independent(combined, algorithm)


def _raw_from_hex(hex_digest: str, algorithm: Algorithm) -> bytes:
    """
    Convert a hex digest back to the raw bytes used for combining.
    For CRCs this is the integer packed as big-endian bytes, not raw hex decode.
    """
    if algorithm == "crc32":
        return struct.pack(">I", int(hex_digest, 16))
    elif algorithm in ("crc64", "crc64nvme"):
        return struct.pack(">Q", int(hex_digest, 16))
    else:
        return bytes.fromhex(hex_digest)


def _hash_stream(stream, algorithm: Algorithm, path: str) -> ChecksumResult:
    """
    Hash a readable binary stream, building a chunk manifest.

    Computes two things in a single pass:
      file_hash   — accumulates ALL bytes through a single streaming hasher.
      per-chunk   — each CHUNK_SIZE block is hashed independently (fresh hasher)
                    and recorded in the manifest.

    The two diverge for CRCs: file_hash is the "true" CRC of the whole file;
    the composite (merkle_root) is the S3-style CRC of concatenated chunk CRCs.
    """
    file_hasher = new_hasher(algorithm)
    chunks: list[ChunkRecord] = []
    offset = 0
    part = 0

    buf = io.BytesIO()
    buf_len = 0

    def flush_chunk(data: bytes) -> None:
        nonlocal offset, part
        chunk_hex = hash_bytes_independent(data, algorithm)
        chunks.append(
            ChunkRecord(
                index=part,
                offset=offset,
                size=len(data),
                hash=chunk_hex,
            )
        )
        file_hasher.update(data)
        offset += len(data)
        part += 1

    for raw in _iter_stream(stream):
        buf.write(raw)
        buf_len += len(raw)
        if buf_len >= CHUNK_SIZE:
            flush_chunk(buf.getvalue())
            buf = io.BytesIO()
            buf_len = 0

    tail = buf.getvalue()
    if tail:
        flush_chunk(tail)

    # Use _raw_from_hex so CRC algorithms produce 4/8-byte packed ints
    # while crypto algorithms produce raw hash bytes
    chunk_raws = [_raw_from_hex(c.hash, algorithm) for c in chunks]
    merkle_root = _combine_child_digests(chunk_raws, algorithm)

    return ChecksumResult(
        path=path,
        algorithm=algorithm,
        file_hash=file_hasher.hexdigest(),
        merkle_root=merkle_root,
        chunk_size=CHUNK_SIZE,
        chunks=chunks,
    )


# ── Local filesystem ───────────────────────────────────────────────────────────


def _hash_local_file(path: str, algorithm: Algorithm) -> ChecksumResult:
    with open(path, "rb") as fh:
        return _hash_stream(fh, algorithm, path)


def _hash_local_dir(path: str, algorithm: Algorithm) -> ChecksumResult:
    """Recursively hash a local directory into a Merkle/composite tree."""
    children: dict[str, ChecksumResult] = {}

    for entry in sorted(os.scandir(path), key=lambda e: e.name):
        if entry.is_file():
            children[entry.name] = _hash_local_file(entry.path, algorithm)
        elif entry.is_dir():
            children[entry.name] = _hash_local_dir(entry.path, algorithm)

    # Each internal node: name bytes + child merkle_root raw bytes
    child_raw = [
        name.encode() + _raw_from_hex(child.merkle_root, algorithm)
        for name, child in children.items()
    ]
    digest = _combine_child_digests(child_raw, algorithm)

    return ChecksumResult(
        path=path,
        algorithm=algorithm,
        file_hash=digest,
        merkle_root=digest,
        is_directory=True,
        children=children,
    )


# ── S3 ─────────────────────────────────────────────────────────────────────────


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Parse s3:// or s3a:// URI into (bucket, key)."""
    for scheme in ("s3://", "s3a://"):
        if uri.startswith(scheme):
            without_scheme = uri[len(scheme) :]
            bucket, _, key = without_scheme.partition("/")
            return bucket, key
    raise ValueError(f"Not an S3 URI: {uri}")


# Maps our algorithm name to the HeadObject response field S3 uses
_S3_NATIVE_RESPONSE_KEY: dict[str, str] = {
    "crc32": "ChecksumCRC32",
    "crc64nvme": "ChecksumCRC64NVME",
}


# Algorithm priority for selection (higher = preferred, computed over native)
ALGORITHM_PRIORITY: dict[str, int] = {
    "blake3": 100,
    "blake2b": 90,
    "crc64": 80,
    "crc64nvme": 70,
    "crc32": 60,
}


def _select_best_algorithm(algorithms: set[str]) -> str | None:
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


def _fetch_all_s3_stored_checksums(
    bucket: str, key: str, s3_client
) -> dict[str, ChecksumResult]:
    """
    Fetch all stored checksums for an S3 object in one HeadObject call.
    Returns dict mapping algorithm name -> ChecksumResult.
    Returns empty dict on any error.
    """
    results: dict[str, ChecksumResult] = {}
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
        for algo in ["blake3", "blake2b", "crc64"]:
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

    Priority order:
      1. S3 native checksum (CRC32, CRC64NVME) — fetched via HeadObject with
         ChecksumMode=ENABLED. Returned as base64, decoded to hex.
      2. User-defined metadata — stored by upload_with_checksum() for algorithms
         S3 doesn't support natively (blake3, blake2b, crc64).

    Returns None if no stored checksum is found for the requested algorithm,
    signalling the caller should fall back to a full download + compute.

    Note on multipart composite:
      For multipart-uploaded objects, S3's native checksum is the *composite*
      (CRC of each part's CRC), not the whole-file CRC. We surface it as both
      file_hash and merkle_root with source='s3_native' so callers can compare
      against their own composite. If you need the true whole-file CRC, you
      must download and compute (pass use_stored=False).
    """
    path = f"s3://{bucket}/{key}"

    # Try S3 native checksum
    if algorithm in _S3_NATIVE_RESPONSE_KEY:
        resp_key = _S3_NATIVE_RESPONSE_KEY[algorithm]
        try:
            head = s3.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
        except Exception:
            return None

        raw_value = head.get(resp_key)
        if raw_value:
            clean_b64 = _strip_multipart_suffix(raw_value)
            hex_digest = _b64_to_hex(clean_b64)
            return ChecksumResult(
                path=path,
                algorithm=algorithm,
                file_hash=hex_digest,
                merkle_root=hex_digest,
                source="s3_native",
                # No chunk manifest available when reading from stored checksum
            )

    # Try user-defined metadata (non-native algorithms)
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
    except Exception:
        return None

    metadata = {k.lower(): v for k, v in head.get("Metadata", {}).items()}
    file_hash = metadata.get(f"x-checksum-{algorithm}")
    merkle_root = metadata.get(f"x-checksum-{algorithm}-merkle")

    if file_hash:
        return ChecksumResult(
            path=path,
            algorithm=algorithm,
            file_hash=file_hash,
            merkle_root=merkle_root or file_hash,
            source="s3_metadata",
        )

    return None


def _find_common_algorithm_in_folder(
    path: str, s3_client
) -> tuple[str | None, dict[str, dict[str, ChecksumResult]]]:
    """
    Find the best common algorithm across all files under a folder.

    Returns:
        (algorithm, per_child_all_checksums)
        - algorithm: highest-priority algorithm shared by ALL children,
                     or None if no common algorithm exists.
        - per_child_all_checksums: dict mapping child_path -> {algo: ChecksumResult}
                                   populated only on success (common algorithm found).
    """
    if not path.startswith(("s3://", "s3a://")):
        return None, {}

    bucket, prefix = _parse_s3_uri(path)
    common_algorithms: set[str] | None = None
    per_child_all_checksums: dict[str, dict[str, ChecksumResult]] = {}

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
    return best_algorithm, per_child_all_checksums


def _hash_s3_file(
    bucket: str,
    key: str,
    algorithm: Algorithm,
    s3,
    use_stored: bool = True,
    cached_results: dict[str, ChecksumResult] | None = None,
) -> ChecksumResult:
    """
    Return a ChecksumResult for an S3 object.

    If cached_results contains a result for this path, return it immediately.
    If use_stored=True (default), checks for a stored S3 checksum first via
    _fetch_s3_stored_checksum. Falls back to streaming download only when no
    stored checksum exists for the requested algorithm.

    Set use_stored=False to always recompute (e.g. for integrity audits).
    """
    path = f"s3://{bucket}/{key}"

    if cached_results and path in cached_results:
        return cached_results[path]

    if use_stored:
        stored = _fetch_s3_stored_checksum(bucket, key, algorithm, s3)
        if stored is not None:
            return stored

    resp = s3.get_object(Bucket=bucket, Key=key)
    return _hash_stream(resp["Body"], algorithm, path)


def insert(tree: dict, parts: list[str], s3_key: str) -> None:
    if len(parts) == 1:
        tree[parts[0]] = ("file", s3_key)
    else:
        tree.setdefault(parts[0], {})
        insert(tree[parts[0]], parts[1:], s3_key)


def _hash_s3_prefix(
    bucket: str,
    prefix: str,
    algorithm: Algorithm,
    s3,
    use_stored: bool = True,
    cached_results: dict[str, ChecksumResult] | None = None,
) -> ChecksumResult:
    """Hash all objects under an S3 prefix as a virtual directory tree."""
    paginator = s3.get_paginator("list_objects_v2")
    keys = sorted(
        obj["Key"]
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix)
        for obj in page.get("Contents", [])
        if not obj["Key"].endswith("/")
    )

    tree: dict = {}
    for key in keys:
        insert(tree, key[len(prefix) :].split("/"), key)

    def hash_tree(node: dict, virtual_path: str) -> ChecksumResult:
        children: dict[str, ChecksumResult] = {}
        for name, value in sorted(node.items()):
            if isinstance(value, tuple) and value[0] == "file":
                children[name] = _hash_s3_file(
                    bucket,
                    value[1],
                    algorithm,
                    s3,
                    use_stored,
                    cached_results,
                )
            elif isinstance(value, dict):
                children[name] = hash_tree(value, f"{virtual_path}{name}/")

        child_raw = [
            name.encode() + _raw_from_hex(child.merkle_root, algorithm)
            for name, child in children.items()
        ]
        digest = _combine_child_digests(child_raw, algorithm)

        return ChecksumResult(
            path=f"s3://{bucket}/{virtual_path}",
            algorithm=algorithm,
            file_hash=digest,
            merkle_root=digest,
            is_directory=True,
            children=children,
        )

    return hash_tree(tree, prefix)


def checksum(
    path: str,
    algorithm: Algorithm = None,
    s3_client=None,
    use_stored: bool = True,
    cached_results: dict[str, ChecksumResult] | None = None,
) -> ChecksumResult:
    """
    Compute a checksum for a file or folder on local disk or S3.
    Args:
        path:        Local path or s3://bucket/key URI (s3a:// also accepted).
                     Trailing slash (or S3 prefix ending in /) = treat as directory.
        algorithm:   One of: blake3 (default), blake2b, crc32, crc64, crc64nvme.
        s3_client:   Optional pre-configured boto3 S3 client. Created automatically
                     for S3 URIs if not provided.
        use_stored:  (S3 only) If True (default), return any checksum already stored
                     on the S3 object — either as a native S3 checksum (CRC32,
                     CRC64NVME) or as user-defined metadata — without downloading
                     the object. Falls back to a full download+compute only when no
                     stored checksum is found for the requested algorithm.
                     Set to False to always recompute (e.g. for integrity audits).
        cached_results: Optional dict of path -> ChecksumResult populated by the
                     detection phase in generate_for_assets(). When provided,
                     S3 file lookups check the cache before fetching or computing.

    Returns:
        ChecksumResult with:
            file_hash            — whole-file digest (hex)
            merkle_root          — Merkle root (crypto) or S3 composite (CRC) (hex)
            source               — "computed", "s3_native", or "s3_metadata"
            s3_base64            — base64(file_hash raw bytes)
            s3_composite_base64  — base64(merkle_root), for CompleteMultipartUpload
            chunks               — per-chunk manifest (files only, when computed)
            children             — per-child results (directories only)
    """
    effective_algorithm = algorithm or "blake3"
    if path.startswith(("s3://", "s3a://")):
        client = s3_client or boto3.client("s3")
        bucket, key = _parse_s3_uri(path)
        if path.endswith("/") or not key:
            return _hash_s3_prefix(
                bucket,
                key,
                effective_algorithm,
                client,
                use_stored,
                cached_results,
            )
        return _hash_s3_file(
            bucket,
            key,
            effective_algorithm,
            client,
            use_stored,
            cached_results,
        )
    else:
        if os.path.isdir(path):
            return _hash_local_dir(path, effective_algorithm)
        return _hash_local_file(path, effective_algorithm)
