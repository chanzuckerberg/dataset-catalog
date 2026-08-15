import os
import sys
from dataclasses import replace
from typing import NamedTuple

from catalog_client.utils.checksum._parallel import (
    local_workers,
    ordered_map,
    s3_workers,
)
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

# The buffer used when hashing through a thread pool. Larger, because the
# buffer size decides how long each update() holds the GIL released, and that
# is what determines whether threads help at all: scaling appears once the
# GIL-free stretch exceeds roughly 25-30us. blake3 clears that at 64KB
# (65536B / 2.1 GB/s ~= 31us), but crc32 and crc64nvme run at 30-48 GB/s and
# spend only ~1.5us per 64KB buffer, so the handoff costs as much as the work
# and eight threads measured *slower* than one. At 1MB they scale 3.3x.
#
# Safe to differ from READ_BUFFER because buffer size is not an input to any
# digest: file_hash never sees a buffer boundary, and chunk boundaries stay
# exact as long as CHUNK_SIZE is a multiple of the buffer (256MB % 1MB == 0).
PARALLEL_READ_BUFFER = 1024 * 1024

# Mean file size at or above which a local tree is hashed through a pool.
# Below it the per-file cost is dominated by open/close syscalls contending in
# the kernel rather than by hashing, and threads measured net-negative on a
# real 16k-file tree averaging 24KB. Derived from the ~25-30us of GIL-free work
# per operation that thread handoff needs to pay for itself: at blake3's
# 2.1 GB/s that is ~60KB, at crc64nvme's 48 GB/s ~1.4MB. 1MB is the cautious
# end of that range, since the algorithm is not known when the gate is applied.
PARALLEL_MIN_MEAN_BYTES = 1024 * 1024

# Below this many files, creating a pool costs more than it saves.
_MIN_FILES_FOR_POOL = 4

# Files per pool task. Dispatch overhead is comparable to the work itself once
# files are small, so batching amortises it.
_FILES_PER_TASK = 128


def _iter_stream(stream, read_buffer: int | None = None):
    """Yield `read_buffer`-sized chunks from any file-like object."""
    # Resolved per call rather than defaulted at def time: the eval harness
    # patches hashing.READ_BUFFER, and a default bound at import would ignore it.
    size = read_buffer or READ_BUFFER
    while True:
        chunk = stream.read(size)
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
    stream,
    algorithm: Algorithm,
    path: str,
    total_size: int | None = None,
    read_buffer: int | None = None,
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

    def close_chunk(final: bool = False) -> None:
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
        # Nothing follows the last chunk, so allocating a hasher for it would
        # throw one away per file — and most files are a single chunk.
        chunk_hasher = None if final else new_hasher(algorithm)

    # Hashers are fed incrementally, so no chunk is ever held in memory: peak
    # usage is one buffer per stream in flight, regardless of CHUNK_SIZE. A
    # chunk is closed only between reads, so boundaries land exactly where a
    # buffered implementation would put them as long as CHUNK_SIZE is a
    # multiple of the buffer (256MB is a multiple of both 64KB and 1MB).
    # file_hash never sees a boundary, so it is unaffected either way; only the
    # manifest and merkle_root would shift.
    # See tests/utils/checksum/test_invariance.py.
    for raw in _iter_stream(stream, read_buffer):
        file_hasher.update(raw)
        if chunk_hasher is not None:
            chunk_hasher.update(raw)
        chunk_len += len(raw)
        if chunk_len >= CHUNK_SIZE:
            close_chunk()

    if chunk_len:
        close_chunk(final=True)

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


def _hash_local_file(
    path: str, algorithm: Algorithm, read_buffer: int | None = None
) -> ChecksumResult:
    with open(path, "rb") as fh:
        # fstat on the open handle rather than os.path.getsize(path): it sizes
        # the exact file being hashed, with no second path lookup and no window
        # for the path to be replaced between the stat and the read.
        size = os.fstat(fh.fileno()).st_size
        return _hash_stream(
            fh, algorithm, path, total_size=size, read_buffer=read_buffer
        )


class _Row(NamedTuple):
    """One entry in a directory listing, as the walk needs it."""

    name: str
    is_dir: bool
    size: int  # 0 for directories; only used to decide whether to use a pool


def _scan_dir(path: str) -> tuple[str, list[_Row]]:
    """List one directory, sorted by name, dropping anything not a file or dir."""
    # `with`, because sorted() consumes the iterator and the fd should close
    # here rather than at the next collection.
    with os.scandir(path) as entries:
        listing = sorted(entries, key=lambda e: e.name)

    rows: list[_Row] = []
    for entry in listing:
        # Both predicates follow symlinks, as they always have: a symlinked
        # file is hashed under the link name and a symlinked directory is
        # descended into. _scan_levels bounds the resulting cycles.
        if entry.is_file():
            rows.append(_Row(entry.name, False, entry.stat().st_size))
        elif entry.is_dir():
            rows.append(_Row(entry.name, True, 0))
    return path, rows


def _scan_levels(
    root: str,
) -> tuple[list[list[str]], dict[str, list[_Row]]]:
    """
    List a tree breadth-first: directory paths per level, and each one's rows.

    Breadth-first rather than recursive for two reasons: it costs no Python
    stack, so nesting depth stops being a limit, and it yields the whole size
    profile before any file is hashed, which is what lets _hash_files decide
    on measured data whether a pool is worth it.

    Deliberately serial. Listing is pure syscall work that the kernel
    serialises anyway, and concurrency makes it monotonically worse: scanning
    16324 files across ~2400 directories on APFS measured 104ms at one thread
    and 203ms at eight. A latency-bound filesystem would want the opposite, but
    that is unmeasured here and the local regression is not.

    Depth is capped because is_dir() follows symlinks. A plain symlink cycle
    is stopped earlier by the kernel's own ELOOP, but nothing else bounds a
    breadth-first walk, which would grow the frontier until memory ran out
    where recursion would have raised RecursionError.
    """
    limit = sys.getrecursionlimit()
    levels: list[list[str]] = []
    rows: dict[str, list[_Row]] = {}
    frontier = [root]

    while frontier:
        if len(levels) >= limit:
            raise RuntimeError(
                f"Directory nesting under {root!r} exceeded {limit} levels at "
                f"{frontier[0]!r}; a symlinked directory cycle is the usual cause"
            )
        levels.append(frontier)
        deeper: list[str] = []
        for directory in frontier:
            scanned, listing = _scan_dir(directory)
            rows[scanned] = listing
            deeper.extend(
                os.path.join(scanned, row.name) for row in listing if row.is_dir
            )
        frontier = deeper

    return levels, rows


def _hash_files(
    paths: list[str], total_bytes: int, algorithm: Algorithm, max_workers: int
) -> dict[str, ChecksumResult]:
    """
    Hash every file in a tree, using a pool only where one actually pays.

    The gate is measured, not guessed: the scan already knows every file and
    its size. Threads win on large files — blake3 measured 3.5x — but lose on
    trees of many small ones, where the cost is `open`/`close` contending in
    the kernel rather than hashing, and 8 workers measured 0.55-0.87x on a real
    16k-file tree. Mean size separates the two cases.
    """
    if not paths:
        return {}

    parallel = (
        max_workers > 1
        and len(paths) > _MIN_FILES_FOR_POOL
        and total_bytes / len(paths) >= PARALLEL_MIN_MEAN_BYTES
    )
    if not parallel:
        return {path: _hash_local_file(path, algorithm) for path in paths}

    # On the caller's thread: initialises any lazy state inside the hasher
    # (crc64 builds its table on first use) and, more importantly, raises a
    # missing optional dependency here rather than out of a worker's future.
    new_hasher(algorithm)

    def hash_batch(batch: list[str]) -> list[tuple[str, ChecksumResult]]:
        return [
            (path, _hash_local_file(path, algorithm, PARALLEL_READ_BUFFER))
            for path in batch
        ]

    # Batch size scales with the work available rather than being fixed. A flat
    # batch of 128 would put a tree of 8 large files into a single task and run
    # it serially — the exact case the pool exists for. Aiming for a few tasks
    # per worker gives one file per task there, and the cap only in trees large
    # enough that per-file dispatch would otherwise cost more than it saves.
    per_task = max(1, min(_FILES_PER_TASK, len(paths) // (max_workers * 4)))
    batches = [paths[i : i + per_task] for i in range(0, len(paths), per_task)]
    results: dict[str, ChecksumResult] = {}
    for done in ordered_map(hash_batch, batches, max_workers):
        results.update(done)
    return results


def _hash_local_dir(
    path: str, algorithm: Algorithm, max_workers: int | None = None
) -> ChecksumResult:
    """
    Hash a local directory into a Merkle/composite tree.

    Three passes: list the structure, hash the files, then fold the tree from
    the leaves up. Splitting them is what lets the middle pass run concurrently
    while keeping the digest identical — children are inserted into each
    directory in the same sorted order the old recursive walk inserted them,
    and _directory_result depends on nothing else.
    """
    workers = local_workers(max_workers)
    levels, rows = _scan_levels(path)

    files = [
        os.path.join(directory, row.name)
        for level in levels
        for directory in level
        for row in rows[directory]
        if not row.is_dir
    ]
    total_bytes = sum(
        row.size
        for level in levels
        for directory in level
        for row in rows[directory]
        if not row.is_dir
    )
    hashed = _hash_files(files, total_bytes, algorithm, workers)

    # Deepest level first, so every child is final before its parent reads it.
    folded: dict[str, ChecksumResult] = {}
    for level in reversed(levels):
        for directory in level:
            children: dict[str, ChecksumResult] = {}
            for row in rows[directory]:
                child = os.path.join(directory, row.name)
                children[row.name] = folded.pop(child) if row.is_dir else hashed[child]
            folded[directory] = _directory_result(directory, children, algorithm)

    return folded[path]


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
    read_buffer: int | None = None,
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
    return _hash_stream(
        resp["Body"], algorithm, path, total_size=size, read_buffer=read_buffer
    )


def _hash_s3_prefix(
    bucket: str,
    prefix: str,
    algorithm: Algorithm,
    s3,
    use_stored: bool = True,
    cached_results: dict[str, ChecksumResult] | None = None,
    max_workers: int | None = None,
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

    # Every object is fetched before the tree is folded, so the walk below sees
    # a completed map and runs exactly as it did serially. Only the order the
    # objects are *retrieved* in changes; the order they are *combined* in is
    # still sorted(node.items()), which is what the digest depends on.
    def fetch(key: str) -> tuple[str, ChecksumResult]:
        return key, _hash_s3_file(
            bucket,
            key,
            algorithm,
            s3,
            use_stored,
            cached_results,
            size=sizes.get(key),
            read_buffer=PARALLEL_READ_BUFFER,
        )

    fetched: dict[str, ChecksumResult] = dict(
        ordered_map(fetch, keys, s3_workers(s3, max_workers))
    )

    def hash_tree(node: dict, virtual_path: str) -> ChecksumResult:
        children: dict[str, ChecksumResult] = {}
        for name, value in sorted(node.items()):
            if isinstance(value, tuple) and value[0] == "file":
                children[name] = fetched[value[1]]
            elif isinstance(value, dict):
                children[name] = hash_tree(value, f"{virtual_path}{name}/")

        return _directory_result(f"s3://{bucket}/{virtual_path}", children, algorithm)

    return hash_tree(tree, prefix)


def compute_checksum_localfs(
    path: str, algorithm: Algorithm, max_workers: int | None = None
) -> ChecksumResult:
    """
    Compute a checksum for a local path (file or directory). Defaults to blake3.

    max_workers caps the threads used to walk a directory; None picks a default
    from the available CPUs and 1 forces the serial path. It has no effect on a
    single file, and never affects the digest.
    """
    if os.path.isdir(path):
        return _hash_local_dir(path, algorithm, max_workers)
    return _hash_local_file(path, algorithm)


def compute_checksum_s3(
    path: str,
    algorithm: Algorithm,
    s3_client=None,
    use_stored: bool = True,
    cached_results: dict[str, ChecksumResult] | None = None,
    is_folder: bool | None = None,
    max_workers: int | None = None,
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
            max_workers,
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
