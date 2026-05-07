"""Tests for compute_checksum_s3 and compute_checksum_localfs.

Each test maps to a numbered use case in docs/compute_checksum_flows.md.
S3 tests use a MagicMock client; local tests use real I/O via tmp_path.
"""

import io
from unittest.mock import MagicMock, patch

from catalog_client.utils.checksum.algorithm import Algorithm
from catalog_client.utils.checksum.hashing import compute_checksum_localfs, compute_checksum_s3
from catalog_client.utils.checksum.models import ChecksumResult

# ── Helpers ───────────────────────────────────────────────────────────────────

BUCKET = "test-bucket"
FILE_KEY = "data/file.h5ad"
FILE_URI = f"s3://{BUCKET}/{FILE_KEY}"
PREFIX = "data/folder/"
PREFIX_URI = f"s3://{BUCKET}/{PREFIX}"
HEX64 = "ab" * 32  # valid 64-char hex (blake3 length)


def _make_result(path, algorithm=Algorithm.blake3, source="computed"):
    return ChecksumResult(path=path, algorithm=algorithm, file_hash=HEX64, merkle_root=HEX64, source=source)


def _s3(head=None, body=b"hello"):
    """S3 client mock with configurable head_object and get_object responses."""
    s3 = MagicMock()
    s3.head_object.return_value = head or {}
    s3.get_object.return_value = {"Body": io.BytesIO(body)}
    return s3


def _s3_prefix(keys, head=None, body=b"hello"):
    """S3 client mock that lists `keys` under a prefix."""
    s3 = _s3(head=head, body=body)
    paginator = MagicMock()
    paginator.paginate.return_value = [{"Contents": [{"Key": k} for k in keys]}]
    s3.get_paginator.return_value = paginator
    return s3


# ── compute_checksum_s3 — path routing ───────────────────────────────────────


def test_s3_file_path_routes_to_object_download():
    # No trailing slash → treated as a file key; get_object called
    s3 = _s3()
    compute_checksum_s3(FILE_URI, Algorithm.blake3, s3, use_stored=False)
    s3.get_object.assert_called_once_with(Bucket=BUCKET, Key=FILE_KEY)


def test_s3_trailing_slash_routes_to_prefix_listing():
    # Trailing slash → treated as a prefix; list_objects_v2 paginator used
    s3 = _s3_prefix(keys=[])
    compute_checksum_s3(PREFIX_URI, Algorithm.blake3, s3)
    s3.get_paginator.assert_called_once_with("list_objects_v2")


# ── compute_checksum_s3 — S3 file (UC 1–4) ───────────────────────────────────


def test_s3_file_cached_result_returned_immediately():
    # UC-1: path in cached_results → return at once; no S3 call
    s3 = _s3()
    cached = {FILE_URI: _make_result(FILE_URI)}
    result = compute_checksum_s3(FILE_URI, Algorithm.blake3, s3, cached_results=cached)
    s3.head_object.assert_not_called()
    s3.get_object.assert_not_called()
    assert result is cached[FILE_URI]


def test_s3_file_stored_checksum_returned_without_download():
    # UC-2: use_stored=True, stored metadata found → return stored; no download
    s3 = _s3(head={"Metadata": {"x-checksum-blake3": HEX64}})
    result = compute_checksum_s3(FILE_URI, Algorithm.blake3, s3, use_stored=True)
    s3.get_object.assert_not_called()
    assert result.file_hash == HEX64
    assert result.source == "s3_metadata"


def test_s3_file_no_stored_checksum_downloads_and_hashes():
    # UC-3: use_stored=True but no stored checksum → fall back to download
    s3 = _s3(head={}, body=b"file content")
    result = compute_checksum_s3(FILE_URI, Algorithm.crc32, s3, use_stored=True)
    s3.get_object.assert_called_once()
    assert result.source == "computed"
    assert result.algorithm == Algorithm.crc32


def test_s3_file_use_stored_false_always_downloads():
    # UC-4: use_stored=False → skip stored checksum check; always download
    s3 = _s3(body=b"data")
    result = compute_checksum_s3(FILE_URI, Algorithm.crc32, s3, use_stored=False)
    s3.head_object.assert_not_called()
    s3.get_object.assert_called_once()
    assert result.source == "computed"


# ── compute_checksum_s3 — S3 prefix / folder (UC 5–11) ───────────────────────


def test_s3_prefix_all_children_cached_no_s3_calls():
    # UC-5: every child already in cached_results → no head_object or get_object
    child_key = f"{PREFIX}file.h5ad"
    child_uri = f"s3://{BUCKET}/{child_key}"
    s3 = _s3_prefix(keys=[child_key])
    cached = {child_uri: _make_result(child_uri)}

    result = compute_checksum_s3(PREFIX_URI, Algorithm.blake3, s3, cached_results=cached)

    s3.head_object.assert_not_called()
    s3.get_object.assert_not_called()
    assert result.is_directory


def test_s3_prefix_some_children_cached_rest_downloaded():
    # UC-6: one child cached, one not — only uncached child is fetched
    cached_key = f"{PREFIX}cached.h5ad"
    missing_key = f"{PREFIX}missing.h5ad"
    cached_uri = f"s3://{BUCKET}/{cached_key}"

    s3 = _s3_prefix(keys=[cached_key, missing_key], head={}, body=b"data")
    cached = {cached_uri: _make_result(cached_uri)}

    compute_checksum_s3(PREFIX_URI, Algorithm.blake3, s3, cached_results=cached)

    # Only the missing child should have triggered a download
    assert s3.get_object.call_count == 1
    assert s3.get_object.call_args.kwargs["Key"] == missing_key


def test_s3_prefix_use_stored_true_stored_checksums_no_download():
    # UC-7: use_stored=True and every child has a stored metadata checksum → no download
    child_key = f"{PREFIX}file.h5ad"
    s3 = _s3_prefix(
        keys=[child_key],
        head={"Metadata": {"x-checksum-blake3": HEX64}},
    )

    result = compute_checksum_s3(PREFIX_URI, Algorithm.blake3, s3, use_stored=True)

    s3.get_object.assert_not_called()
    assert result.is_directory


def test_s3_prefix_use_stored_true_no_stored_downloads():
    # UC-8: use_stored=True but no stored checksum on children → downloads
    child_key = f"{PREFIX}file.h5ad"
    s3 = _s3_prefix(keys=[child_key], head={}, body=b"data")

    compute_checksum_s3(PREFIX_URI, Algorithm.blake3, s3, use_stored=True)

    s3.get_object.assert_called_once()


def test_s3_prefix_use_stored_false_downloads_all_children():
    # UC-9: use_stored=False → all children downloaded regardless of stored checksums
    keys = [f"{PREFIX}a.h5ad", f"{PREFIX}b.h5ad"]
    s3 = _s3_prefix(keys=keys, body=b"data")

    compute_checksum_s3(PREFIX_URI, Algorithm.blake3, s3, use_stored=False)

    assert s3.get_object.call_count == 2
    s3.head_object.assert_not_called()


def test_s3_prefix_virtual_subdirectories_hashed_recursively():
    # UC-10: keys with sub-paths create virtual directory nodes in the tree
    keys = [f"{PREFIX}subdir/a.h5ad", f"{PREFIX}subdir/b/c.h5ad"]
    s3 = _s3_prefix(keys=keys, body=b"data")

    result = compute_checksum_s3(PREFIX_URI, Algorithm.blake3, s3, use_stored=False)

    assert result.is_directory
    assert "subdir" in result.children
    assert result.children["subdir"].is_directory
    assert "b" in result.children["subdir"].children
    assert result.children["subdir"].children["b"].is_directory


def test_s3_prefix_empty_prefix_returns_hash_of_empty():
    # UC-11: no objects under prefix → Merkle of empty child list (hash of empty bytes)
    s3 = _s3_prefix(keys=[])

    result = compute_checksum_s3(PREFIX_URI, Algorithm.blake3, s3)

    assert result.is_directory
    assert result.children == {}
    assert result.file_hash is not None  # deterministic hash of empty bytes
    assert result.file_hash == result.merkle_root


# ── compute_checksum_localfs — path routing ───────────────────────────────────


def test_localfs_file_path_is_not_directory(tmp_path):
    f = tmp_path / "file.txt"
    f.write_bytes(b"hello")
    result = compute_checksum_localfs(str(f), Algorithm.blake3)
    assert not result.is_directory


def test_localfs_directory_path_is_directory(tmp_path):
    result = compute_checksum_localfs(str(tmp_path), Algorithm.blake3)
    assert result.is_directory


# ── compute_checksum_localfs — local file chunk behaviour ────────────────────


def test_localfs_single_chunk_streaming_hash_equals_chunk_hash(tmp_path):
    # For a single-chunk file, the whole-file streaming hash equals the single chunk's
    # independently-computed hash — both cover the same data with a fresh hasher.
    # merkle_root is always hash(raw_bytes_of(chunk_hash)), which differs from file_hash.
    f = tmp_path / "small.txt"
    f.write_bytes(b"hello world")
    result = compute_checksum_localfs(str(f), Algorithm.blake3)
    assert len(result.chunks) == 1
    assert result.file_hash == result.chunks[0].hash


@patch("catalog_client.utils.checksum.hashing.READ_BUFFER", 4)
@patch("catalog_client.utils.checksum.hashing.CHUNK_SIZE", 4)
def test_localfs_multi_chunk_crc_streaming_hash_differs_from_chunk_and_merkle(tmp_path):
    # CRC multi-chunk: file_hash = streaming CRC of full data (one pass);
    # chunks[0].hash = CRC of first chunk only → differs from file_hash;
    # merkle_root = CRC of concatenated packed chunk CRC integers → also differs.
    # READ_BUFFER is patched so each 4-byte read triggers a chunk flush.
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello world")  # 11 bytes → chunks: b"hell", b"o wo", b"rld"
    result = compute_checksum_localfs(str(f), Algorithm.crc32)
    assert len(result.chunks) == 3
    assert result.file_hash != result.chunks[0].hash
    assert result.file_hash != result.merkle_root


@patch("catalog_client.utils.checksum.hashing.READ_BUFFER", 4)
@patch("catalog_client.utils.checksum.hashing.CHUNK_SIZE", 4)
def test_localfs_multi_chunk_crypto_streaming_hash_differs_from_chunk_and_merkle(tmp_path):
    # Crypto multi-chunk: file_hash = hash of full byte stream;
    # merkle_root = hash of concatenated raw chunk hashes — both differ from chunks[0].hash.
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello world")
    result = compute_checksum_localfs(str(f), Algorithm.blake2b)
    assert len(result.chunks) == 3
    assert result.file_hash != result.chunks[0].hash
    assert result.file_hash != result.merkle_root


@patch("catalog_client.utils.checksum.hashing.READ_BUFFER", 4)
@patch("catalog_client.utils.checksum.hashing.CHUNK_SIZE", 4)
def test_localfs_chunks_list_has_correct_offsets(tmp_path):
    # 8-byte file with 4-byte chunk size → exactly 2 chunks
    f = tmp_path / "data.bin"
    f.write_bytes(b"abcdefgh")
    result = compute_checksum_localfs(str(f), Algorithm.crc32)
    assert len(result.chunks) == 2
    assert result.chunks[0].offset == 0
    assert result.chunks[0].size == 4
    assert result.chunks[1].offset == 4
    assert result.chunks[1].size == 4


def test_localfs_same_content_same_hash(tmp_path):
    # Determinism: identical content → identical hash regardless of filename
    content = b"deterministic content"
    (tmp_path / "a.txt").write_bytes(content)
    (tmp_path / "b.txt").write_bytes(content)
    r1 = compute_checksum_localfs(str(tmp_path / "a.txt"), Algorithm.blake3)
    r2 = compute_checksum_localfs(str(tmp_path / "b.txt"), Algorithm.blake3)
    assert r1.file_hash == r2.file_hash


# ── compute_checksum_localfs — local directory (UC 12–15) ────────────────────


def test_localfs_directory_files_only(tmp_path):
    # UC-12: directory with only files → Merkle over name+hash pairs
    (tmp_path / "a.txt").write_bytes(b"aaa")
    (tmp_path / "b.txt").write_bytes(b"bbb")

    result = compute_checksum_localfs(str(tmp_path), Algorithm.blake3)

    assert result.is_directory
    assert result.file_hash == result.merkle_root
    assert set(result.children.keys()) == {"a.txt", "b.txt"}
    assert not result.children["a.txt"].is_directory


def test_localfs_directory_with_subdirectories(tmp_path):
    # UC-13: subdirectories are hashed recursively
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "child.txt").write_bytes(b"child")

    result = compute_checksum_localfs(str(tmp_path), Algorithm.blake3)

    assert "subdir" in result.children
    assert result.children["subdir"].is_directory
    assert "child.txt" in result.children["subdir"].children


def test_localfs_empty_directory(tmp_path):
    # UC-14: empty directory → hash of empty bytes; no children
    result = compute_checksum_localfs(str(tmp_path), Algorithm.blake3)

    assert result.is_directory
    assert result.children == {}
    assert result.file_hash is not None
    assert result.file_hash == result.merkle_root


def test_localfs_directory_mixed_files_and_subdirs(tmp_path):
    # UC-15: directory with both files and sub-directories
    (tmp_path / "file.txt").write_bytes(b"data")
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_bytes(b"nested")

    result = compute_checksum_localfs(str(tmp_path), Algorithm.blake3)

    assert "file.txt" in result.children
    assert "subdir" in result.children
    assert not result.children["file.txt"].is_directory
    assert result.children["subdir"].is_directory


def test_localfs_directory_children_sorted_by_name(tmp_path):
    # Merkle is computed in sorted name order; verify children keys are sorted
    for name in ["c.txt", "a.txt", "b.txt"]:
        (tmp_path / name).write_bytes(name.encode())

    result = compute_checksum_localfs(str(tmp_path), Algorithm.blake3)

    assert list(result.children.keys()) == sorted(result.children.keys())


def test_localfs_directory_hash_changes_with_content(tmp_path):
    # Merkle root must reflect content — adding a file changes the digest
    (tmp_path / "a.txt").write_bytes(b"original")
    result_before = compute_checksum_localfs(str(tmp_path), Algorithm.blake3)

    (tmp_path / "b.txt").write_bytes(b"extra")
    result_after = compute_checksum_localfs(str(tmp_path), Algorithm.blake3)

    assert result_before.merkle_root != result_after.merkle_root
