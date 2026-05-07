import io
import os
import struct

from catalog_client.utils.checksum.algorithm import Algorithm, hash_bytes_independent, new_hasher
from catalog_client.utils.checksum.models import CHUNK_SIZE, ChecksumResult, ChunkRecord
from catalog_client.utils.checksum.s3 import _fetch_s3_stored_checksum, _parse_s3_uri

READ_BUFFER = 64 * 1024  # 64KB I/O buffer


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
            buf.seek(0)
            buf.truncate()
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


# ── Local filesystem ────────────────────────────────────────────────────────────


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
    child_raw = [name.encode() + _raw_from_hex(child.merkle_root, algorithm) for name, child in children.items()]
    digest = _combine_child_digests(child_raw, algorithm)

    return ChecksumResult(
        path=path,
        algorithm=algorithm,
        file_hash=digest,
        merkle_root=digest,
        is_directory=True,
        children=children,
    )


# ── S3 ──────────────────────────────────────────────────────────────────────────


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

        child_raw = [name.encode() + _raw_from_hex(child.merkle_root, algorithm) for name, child in children.items()]
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


def compute_checksum_localfs(path: str, algorithm: Algorithm) -> ChecksumResult:
    """
    Compute a checksum for a local path (file or directory). Defaults to blake3.
    """
    if os.path.isdir(path):
        return _hash_local_dir(path, algorithm)
    return _hash_local_file(path, algorithm)


def compute_checksum_s3(
    path: str,
    algorithm: Algorithm,
    s3_client=None,
    use_stored: bool = True,
    cached_results: dict[str, ChecksumResult] | None = None,
) -> ChecksumResult:
    """
    Compute a checksum for an S3 URI (s3:// or s3a://). Defaults to blake3.
    Trailing slash = treat as prefix (virtual directory).

    use_stored=True (default) returns any checksum already on the S3 object
    without downloading. Set False to always recompute (e.g. integrity audits).
    """
    bucket, key = _parse_s3_uri(path)
    if path.endswith("/") or not key:
        return _hash_s3_prefix(bucket, key, algorithm, s3_client, use_stored, cached_results)
    return _hash_s3_file(bucket, key, algorithm, s3_client, use_stored, cached_results)


def compute_checksum(
    path: str,
    algorithm: Algorithm,
    s3_client=None,
    use_stored: bool = True,
    cached_results: dict[str, ChecksumResult] | None = None,
) -> ChecksumResult:
    """
    Compute a checksum for a local path or S3 URI (s3:// or s3a://).
    Delegates to compute_checksum_s3 or compute_checksum_localfs.
    """
    if path.startswith(("s3://", "s3a://")):
        return compute_checksum_s3(path, algorithm, s3_client, use_stored, cached_results)
    return compute_checksum_localfs(path, algorithm)
