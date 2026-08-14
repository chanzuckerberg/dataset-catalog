import os
from dataclasses import replace

from catalog_client.utils.checksum.algorithm import (
    Algorithm,
    _Hasher,
    hash_bytes_independent,
    new_hasher,
    raw_from_hex,
)
from catalog_client.utils.checksum.models import CHUNK_SIZE, ChecksumResult, ChunkRecord
from catalog_client.utils.checksum.s3 import (
    _fetch_s3_stored_checksum,
    _folder_prefix,
    _insert_key,
    _parse_s3_uri,
)

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
        Computes CRC over the concatenated raw child CRC bytes. For the chunks
        of a single file this matches S3's composite checksum model for
        multipart uploads. Directory nodes prepend each child's name (see
        _directory_result), so directory digests are deliberately NOT
        S3-composite-compatible — S3 composites cover ordered, unnamed parts.

    Both cases use the same operation: hash/CRC of concatenated raw bytes.
    The difference is only in what "raw bytes" means per algorithm type:
    - crypto  → raw bytes of the hex digest
    - crc32   → 4 big-endian bytes of the CRC integer
    - crc64*  → 8 big-endian bytes of the CRC integer
    """
    combined = b"".join(raw_digests)
    return hash_bytes_independent(combined, algorithm)


def _sum_child_sizes(children: dict[str, ChecksumResult]) -> int | None:
    """
    Total the byte sizes of a directory's children.

    Returns None if any child's size is unknown: a partial sum would understate
    the directory and read as authoritative. An empty directory totals 0.
    """
    total = 0
    for child in children.values():
        if child.total_size is None:
            return None
        total += child.total_size
    return total


def _directory_result(
    path: str, children: dict[str, ChecksumResult], algorithm: Algorithm
) -> ChecksumResult:
    """
    Build the tree node for a directory (local or S3 prefix) from its children.

    Each child contributes its name bytes plus the raw bytes of its
    content_digest, so a rename changes the parent digest even when file
    contents are identical.

    content_digest — not merkle_root — is what makes folder hashing
    reproducible: it is the same value the child would report if checksummed
    standalone, so a child read from a stored S3 checksum and the same child
    downloaded and hashed contribute identical bytes to the parent.
    """
    child_raw = [
        name.encode() + raw_from_hex(child.content_digest, algorithm)
        for name, child in children.items()
    ]
    digest = _combine_child_digests(child_raw, algorithm)

    return ChecksumResult(
        path=path,
        algorithm=algorithm,
        file_hash=digest,
        merkle_root=digest,
        is_directory=True,
        total_size=_sum_child_sizes(children),
        children=children,
    )


def _hash_stream(
    stream, algorithm: Algorithm, path: str, total_size: int | None = None
) -> ChecksumResult:
    """
    Hash a readable binary stream, building a chunk manifest.

    Computes two things in a single pass:
      file_hash   — accumulates ALL bytes through a single streaming hasher.
      per-chunk   — each CHUNK_SIZE block is hashed independently and recorded
                    in the manifest. Chunk 0 reuses the whole-file hasher's
                    state at the boundary instead of running a parallel hasher;
                    chunks 1+ get their own. See close_chunk.

    The two diverge for CRCs: file_hash is the "true" CRC of the whole file;
    the composite (merkle_root) is the S3-style CRC of concatenated chunk CRCs.

    total_size is supplied by the caller from storage-platform metadata and is
    passed straight through — it is never derived by counting bytes here.
    Deriving it here would only produce a size on the paths that read the whole
    object, leaving the stored-checksum fast path (which never enters this
    function) sizeless.
    """
    file_hasher = new_hasher(algorithm)
    # Deliberately not created yet. Chunk 0 begins at offset 0, so the whole-file
    # hasher's state when chunk 0 closes IS the independent hash of chunk 0 —
    # a second hasher over those same bytes would recompute a value already in
    # hand. Since CHUNK_SIZE is 256MB, most real files are single-chunk and
    # never allocate one at all, halving the per-byte hashing work. Chunk 1
    # onward do need their own hasher, created when chunk 0 closes.
    chunk_hasher: _Hasher | None = None
    chunks: list[ChunkRecord] = []
    offset = 0
    chunk_len = 0

    def close_chunk() -> None:
        """Record the chunk accumulated so far and start a fresh chunk hasher."""
        nonlocal chunk_hasher, offset, chunk_len
        # hexdigest() is a non-destructive read of hasher state for every
        # algorithm here (blake3, hashlib, and the CRC wrappers), so snapshotting
        # file_hasher mid-stream leaves it able to keep consuming the rest.
        digest = (
            file_hasher.hexdigest()
            if chunk_hasher is None
            else chunk_hasher.hexdigest()
        )
        chunks.append(
            ChunkRecord(
                index=len(chunks),
                offset=offset,
                size=chunk_len,
                hash=digest,
            )
        )
        offset += chunk_len
        chunk_len = 0
        chunk_hasher = new_hasher(algorithm)

    # Hashers are fed incrementally, so no chunk is ever held in memory:
    # peak usage is one READ_BUFFER regardless of CHUNK_SIZE. A chunk is closed
    # only between reads, so boundaries land exactly where a buffered
    # implementation would put them as long as CHUNK_SIZE is a multiple of
    # READ_BUFFER (256MB and 64KB are). file_hash never sees a boundary, so it
    # is unaffected either way; only the manifest and merkle_root would shift.
    # See tests/utils/checksum/test_invariance.py.
    for raw in _iter_stream(stream):
        file_hasher.update(raw)
        if chunk_hasher is not None:
            chunk_hasher.update(raw)
        chunk_len += len(raw)
        if chunk_len >= CHUNK_SIZE:
            close_chunk()

    if chunk_len:
        close_chunk()

    # Use raw_from_hex so CRC algorithms produce 4/8-byte packed ints
    # while crypto algorithms produce raw hash bytes
    chunk_raws = [raw_from_hex(c.hash, algorithm) for c in chunks]
    merkle_root = _combine_child_digests(chunk_raws, algorithm)

    return ChecksumResult(
        path=path,
        algorithm=algorithm,
        file_hash=file_hasher.hexdigest(),
        merkle_root=merkle_root,
        total_size=total_size,
        chunks=chunks,
    )


# ── Local filesystem ────────────────────────────────────────────────────────────


def _hash_local_file(path: str, algorithm: Algorithm) -> ChecksumResult:
    with open(path, "rb") as fh:
        # fstat on the open handle rather than os.path.getsize(path): it sizes
        # the exact file being hashed, with no second path lookup and no window
        # for the path to be replaced between the stat and the read.
        size = os.fstat(fh.fileno()).st_size
        return _hash_stream(fh, algorithm, path, total_size=size)


def _hash_local_dir(path: str, algorithm: Algorithm) -> ChecksumResult:
    """Recursively hash a local directory into a Merkle/composite tree."""
    children: dict[str, ChecksumResult] = {}

    for entry in sorted(os.scandir(path), key=lambda e: e.name):
        if entry.is_file():
            children[entry.name] = _hash_local_file(entry.path, algorithm)
        elif entry.is_dir():
            children[entry.name] = _hash_local_dir(entry.path, algorithm)

    return _directory_result(path, children, algorithm)


# ── S3 ──────────────────────────────────────────────────────────────────────────


def _with_size(result: ChecksumResult, size: int | None) -> ChecksumResult:
    """
    Backfill a known size onto a result that does not carry one.

    A result read from HeadObject or the cache normally already knows its size;
    this covers the case where it does not but the listing does. Returns a copy
    rather than mutating, because cached results are shared between the folder
    walk and the caller's cache dict. A size the result already has is left
    alone — HeadObject and the listing agree, and preferring one arbitrarily
    would make the value depend on call order.
    """
    if size is None or result.total_size is not None:
        return result
    return replace(result, total_size=size)


def _hash_s3_file(
    bucket: str,
    key: str,
    algorithm: Algorithm,
    s3,
    use_stored: bool = True,
    cached_results: dict[str, ChecksumResult] | None = None,
    size: int | None = None,
) -> ChecksumResult:
    """
    Return a ChecksumResult for an S3 object.

    If cached_results contains a result for this path, return it immediately.
    If use_stored=True (default), checks for a stored S3 checksum first via
    _fetch_s3_stored_checksum. Falls back to streaming download only when no
    stored checksum exists for the requested algorithm.

    Set use_stored=False to always recompute (e.g. for integrity audits).

    size is the object's byte size if the caller already knows it (the prefix
    walk reads it from the listing). Cache hits and stored checksums carry a
    size of their own from HeadObject; size only fills in for them when that is
    missing. Otherwise the size comes off the GetObject response already being
    issued — never from counting bytes.
    """
    path = f"s3://{bucket}/{key}"

    if cached_results and path in cached_results:
        return _with_size(cached_results[path], size)

    if use_stored:
        stored = _fetch_s3_stored_checksum(bucket, key, algorithm, s3)
        if stored is not None:
            return _with_size(stored, size)

    resp = s3.get_object(Bucket=bucket, Key=key)
    # .get, not []: GetObject always returns ContentLength in practice, but the
    # test suite builds partial response dicts, and a missing size is reportable
    # (None) rather than fatal.
    if size is None:
        size = resp.get("ContentLength")
    return _hash_stream(resp["Body"], algorithm, path, total_size=size)


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
    # The listing already reports every object's size, so a folder's total is
    # known from this one call regardless of how each child's digest is later
    # obtained (cache, stored checksum, or download).
    sizes: dict[str, int | None] = {
        obj["Key"]: obj.get("Size")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix)
        for obj in page.get("Contents", [])
        if not obj["Key"].endswith("/")
    }
    keys = sorted(sizes)

    tree: dict = {}
    for key in keys:
        _insert_key(tree, key[len(prefix) :].split("/"), key)

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
                    size=sizes.get(value[1]),
                )
            elif isinstance(value, dict):
                children[name] = hash_tree(value, f"{virtual_path}{name}/")

        return _directory_result(f"s3://{bucket}/{virtual_path}", children, algorithm)

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
    is_folder: bool | None = None,
) -> ChecksumResult:
    """
    Compute a checksum for an S3 URI (s3:// or s3a://).

    is_folder=True treats the key as a prefix (virtual directory), False as a
    single object. When None (the default) it is inferred from the URI: a
    trailing slash or an empty key means prefix. Callers that already know the
    asset type should pass it explicitly rather than relying on the caller
    having appended a slash.

    use_stored=True (default) returns any checksum already on the S3 object
    without downloading. Set False to always recompute (e.g. integrity audits).
    """
    bucket, key = _parse_s3_uri(path)
    if is_folder is None:
        is_folder = path.endswith("/") or not key
    if is_folder:
        return _hash_s3_prefix(
            bucket,
            _folder_prefix(key),
            algorithm,
            s3_client,
            use_stored,
            cached_results,
        )
    return _hash_s3_file(bucket, key, algorithm, s3_client, use_stored, cached_results)


def compute_checksum(
    path: str,
    algorithm: Algorithm,
    s3_client=None,
    use_stored: bool = True,
    cached_results: dict[str, ChecksumResult] | None = None,
    is_folder: bool | None = None,
) -> ChecksumResult:
    """
    Compute a checksum for a local path or S3 URI (s3:// or s3a://).
    Delegates to compute_checksum_s3 or compute_checksum_localfs.

    is_folder is only consulted for S3 URIs; local paths are classified by
    os.path.isdir.
    """
    if path.startswith(("s3://", "s3a://")):
        return compute_checksum_s3(
            path, algorithm, s3_client, use_stored, cached_results, is_folder
        )
    return compute_checksum_localfs(path, algorithm)
