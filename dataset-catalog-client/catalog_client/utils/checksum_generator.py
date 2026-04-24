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
    assert uri.startswith("s3://"), f"Not an S3 URI: {uri}"
    without_scheme = uri[5:]
    bucket, _, key = without_scheme.partition("/")
    return bucket, key


# Maps our algorithm name to the HeadObject response field S3 uses
_S3_NATIVE_RESPONSE_KEY: dict[str, str] = {
    "crc32": "ChecksumCRC32",
    "crc64nvme": "ChecksumCRC64NVME",
}


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


def _hash_s3_file(
    bucket: str,
    key: str,
    algorithm: Algorithm,
    s3,
    use_stored: bool = True,
) -> ChecksumResult:
    """
    Return a ChecksumResult for an S3 object.

    If use_stored=True (default), checks for a stored S3 checksum first via
    _fetch_s3_stored_checksum. Falls back to streaming download only when no
    stored checksum exists for the requested algorithm.

    Set use_stored=False to always recompute (e.g. for integrity audits).
    """
    if use_stored:
        stored = _fetch_s3_stored_checksum(bucket, key, algorithm, s3)
        if stored is not None:
            return stored

    resp = s3.get_object(Bucket=bucket, Key=key)
    return _hash_stream(resp["Body"], algorithm, f"s3://{bucket}/{key}")


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
                    bucket, value[1], algorithm, s3, use_stored
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
    algorithm: Algorithm = "blake3",
    s3_client=None,
    use_stored: bool = True,
) -> ChecksumResult:
    """
    Compute a checksum for a file or folder on local disk or S3.
    Args:
        path:        Local path or s3://bucket/key URI.
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
    if path.startswith("s3://"):
        client = s3_client or boto3.client("s3")
        bucket, key = _parse_s3_uri(path)
        if path.endswith("/") or not key:
            return _hash_s3_prefix(bucket, key, algorithm, client, use_stored)
        return _hash_s3_file(bucket, key, algorithm, client, use_stored)
    else:
        if os.path.isdir(path):
            return _hash_local_dir(path, algorithm)
        return _hash_local_file(path, algorithm)
