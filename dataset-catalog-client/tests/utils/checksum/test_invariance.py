"""A digest must not depend on how the bytes were read.

CHUNK_SIZE is 256MB and READ_BUFFER is 64KB in production, so no other test in
this package ever produces a second chunk or a second read. That leaves the
whole chunking path — the manifest, the composite, and the loop that feeds two
hashers at once — unexercised for the property the checksums exist for.

These tests shrink both constants so chunking actually happens, then assert:

  content_digest   invariant under every chunk size and every read buffer
                   (this is the value stored on an asset, so it is the promise)
  merkle_root      invariant under read buffer, but deliberately NOT under
                   chunk size — it describes a specific partitioning
                   (see test_s3_conformance.py for why that partitioning matters)

Both constants are patched on `hashing`, not `models`: hashing.py binds
CHUNK_SIZE by value at import, so patching models.CHUNK_SIZE has no effect.
"""

import pytest

from catalog_client.utils.checksum import hashing
from catalog_client.utils.checksum.algorithm import Algorithm, hash_bytes_independent
from catalog_client.utils.checksum.hashing import compute_checksum_localfs

ALGORITHMS = [
    Algorithm.blake2b,
    Algorithm.crc32,
    Algorithm.blake3,
    Algorithm.crc64,
    Algorithm.crc64nvme,
]
algorithms = pytest.mark.parametrize(
    "algorithm", ALGORITHMS, ids=[a.value for a in ALGORITHMS]
)

PRODUCTION_CHUNK_SIZE = 256 * 1024 * 1024

# A 251-byte (prime) pattern, so no chunk or buffer boundary can land on the
# pattern period and hide an off-by-one in the read loop.
_PATTERN = bytes(range(251))


def payload(size: int) -> bytes:
    return (_PATTERN * (size // len(_PATTERN) + 1))[:size]


BODY = payload(1000)


@pytest.fixture
def hashed(tmp_path, monkeypatch):
    """Hash a body under a chosen chunk size and read buffer."""

    def run(algorithm, chunk_size, read_buffer, body=BODY):
        monkeypatch.setattr(hashing, "CHUNK_SIZE", chunk_size)
        monkeypatch.setattr(hashing, "READ_BUFFER", read_buffer)
        path = tmp_path / "f.bin"
        path.write_bytes(body)
        return compute_checksum_localfs(str(path), algorithm)

    return run


@pytest.fixture
def chunking(monkeypatch):
    """Set the chunk size and read buffer for code paths called directly."""

    def apply(chunk_size, read_buffer):
        monkeypatch.setattr(hashing, "CHUNK_SIZE", chunk_size)
        monkeypatch.setattr(hashing, "READ_BUFFER", read_buffer)

    return apply


# ── content_digest is independent of how the file was partitioned ─────────────


@algorithms
@pytest.mark.parametrize(
    "chunk_size", [1, 7, 64, 999, 1000, 1001, PRODUCTION_CHUNK_SIZE]
)
def test_content_digest_is_independent_of_chunk_size(hashed, algorithm, chunk_size):
    """The stored digest must survive any future change to CHUNK_SIZE.

    read_buffer=1 so the chunk boundary lands exactly at chunk_size for every
    case, including chunk sizes below the production 64KB buffer.
    """
    baseline = hashed(algorithm, PRODUCTION_CHUNK_SIZE, 1).content_digest
    assert hashed(algorithm, chunk_size, 1).content_digest == baseline


@algorithms
@pytest.mark.parametrize("read_buffer", [1, 3, 64, 251, 1000, 64 * 1024, 10**6])
def test_content_digest_is_independent_of_read_buffer(hashed, algorithm, read_buffer):
    baseline = hashed(algorithm, 128, 1).content_digest
    assert hashed(algorithm, 128, read_buffer).content_digest == baseline


@algorithms
@pytest.mark.parametrize("size", [0, 1, 127, 128, 129, 255, 256, 257, 1000])
def test_content_digest_is_the_same_chunked_or_not_at_every_boundary(
    hashed, algorithm, size
):
    """Sizes either side of one, two and multiple chunks of 128 bytes."""
    body = payload(size)
    chunked = hashed(algorithm, 128, 1, body).content_digest
    unchunked = hashed(algorithm, PRODUCTION_CHUNK_SIZE, 10**6, body).content_digest
    assert chunked == unchunked


# ── merkle_root describes a partitioning, so it does depend on chunk size ─────


@algorithms
def test_merkle_root_changes_with_chunk_size(hashed, algorithm):
    """Reproducibility of content_digest must not be mistaken for merkle_root.

    merkle_root is the S3 composite / Merkle root over a specific partitioning.
    Two different partitionings of the same bytes are two different values, and
    conflating them is how a composite checksum gets stored as if it were a
    whole-object one.
    """
    ten_chunks = hashed(algorithm, 100, 1)
    one_chunk = hashed(algorithm, 1000, 1)

    assert len(ten_chunks.chunks) == 10
    assert len(one_chunk.chunks) == 1
    assert ten_chunks.merkle_root != one_chunk.merkle_root
    assert ten_chunks.content_digest == one_chunk.content_digest


@algorithms
@pytest.mark.parametrize("read_buffer", [1, 2, 4, 64, 128])
def test_merkle_root_is_stable_while_the_read_buffer_divides_the_chunk(
    hashed, algorithm, read_buffer
):
    """Every buffer here divides CHUNK_SIZE=128 exactly, as production does."""
    baseline = hashed(algorithm, 128, 1).merkle_root
    assert hashed(algorithm, 128, read_buffer).merkle_root == baseline


@algorithms
@pytest.mark.parametrize("read_buffer", [3, 1000])
def test_a_read_buffer_that_does_not_divide_the_chunk_shifts_the_manifest(
    hashed, algorithm, read_buffer
):
    """The one constraint the read loop imposes, made explicit.

    _hash_stream tests `chunk_len >= CHUNK_SIZE` only between read() calls, so
    chunk boundaries are exact only while CHUNK_SIZE is an exact multiple of
    READ_BUFFER. Production satisfies that (256MB is a multiple of 64KB); a
    buffer of 3 against a 128-byte chunk does not, and closes chunks at 129.

    content_digest is unaffected in every case — file_hasher never sees a chunk
    boundary — which is why the *stored* digest is safe regardless. Only the
    manifest and the composite shift, so this is a guard on the assumption, not
    a live defect. Widen with care: changing it rewrites every merkle_root.
    """
    exact = hashed(algorithm, 128, 1)
    shifted = hashed(algorithm, 128, read_buffer)

    assert [c.size for c in exact.chunks] == [128, 128, 128, 128, 128, 128, 128, 104]
    assert [c.size for c in shifted.chunks] != [c.size for c in exact.chunks]
    assert exact.merkle_root != shifted.merkle_root
    assert exact.content_digest == shifted.content_digest


@pytest.mark.parametrize(
    "buffer_name", ["READ_BUFFER", "PARALLEL_READ_BUFFER"], ids=["serial", "parallel"]
)
def test_every_production_read_buffer_divides_the_chunk_size(buffer_name):
    """The precondition the test above describes, asserted on the real values.

    There are two production buffers — pooled reads use a larger one, because
    buffer size decides how long each update() holds the GIL released. They may
    differ freely, since content_digest does not depend on the buffer at all,
    but each must still divide CHUNK_SIZE or the manifest it produces would not
    match the pinned golden vectors.
    """
    read_buffer = getattr(hashing, buffer_name)
    assert hashing.CHUNK_SIZE % read_buffer == 0, (
        f"CHUNK_SIZE={hashing.CHUNK_SIZE} is not a multiple of "
        f"{buffer_name}={read_buffer}; chunk boundaries would shift"
    )


@algorithms
def test_a_read_buffer_larger_than_the_file_yields_a_single_chunk(hashed, algorithm):
    """The degenerate end of the same constraint: one read, one chunk."""
    coarsened = hashed(algorithm, 100, 10**6)

    assert len(coarsened.chunks) == 1
    assert coarsened.chunks[0].size == len(BODY)
    assert coarsened.content_digest == hashed(algorithm, 100, 1).content_digest


# ── The manifest describes the file it came from ──────────────────────────────


@algorithms
@pytest.mark.parametrize("chunk_size", [1, 7, 128, 1000, 1001])
def test_chunk_manifest_tiles_the_file_exactly(hashed, algorithm, chunk_size):
    result = hashed(algorithm, chunk_size, 1)

    assert [c.index for c in result.chunks] == list(range(len(result.chunks)))
    assert sum(c.size for c in result.chunks) == len(BODY)

    offset = 0
    for chunk in result.chunks:
        assert chunk.offset == offset
        assert chunk.hash == hash_bytes_independent(
            BODY[offset : offset + chunk.size], algorithm
        )
        offset += chunk.size


@algorithms
def test_an_empty_file_has_no_chunks_but_still_has_a_digest(hashed, algorithm):
    result = hashed(algorithm, 128, 1, b"")

    assert result.chunks == []
    assert result.content_digest == hash_bytes_independent(b"", algorithm)
    # An empty chunk list combines to the digest of no bytes.
    assert result.merkle_root == hash_bytes_independent(b"", algorithm)


# ── The folder property holds for chunked children too ───────────────────────


@algorithms
def test_chunked_child_matches_its_standalone_digest(tmp_path, chunking, algorithm):
    """Claim 2, under conditions where the child is split into many chunks.

    A file large enough to chunk is exactly where a folder walk and a standalone
    hash could diverge, since only one of the two paths would be reading a
    manifest.
    """
    chunking(100, 7)
    folder = tmp_path / "ds"
    folder.mkdir()
    (folder / "big.bin").write_bytes(BODY)

    standalone = compute_checksum_localfs(str(folder / "big.bin"), algorithm)
    as_child = compute_checksum_localfs(str(folder), algorithm).children["big.bin"]

    assert len(standalone.chunks) == 10
    assert standalone.content_digest == as_child.content_digest


@algorithms
def test_folder_digest_is_independent_of_chunk_size(tmp_path, chunking, algorithm):
    """A folder root is built from children's content_digest, so it inherits
    chunk-size independence. This is the assertion that would fail if
    _directory_result were ever switched to combine merkle_root instead."""
    folder = tmp_path / "ds"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.bin").write_bytes(BODY)
    (folder / "sub" / "b.bin").write_bytes(payload(777))

    roots = set()
    for chunk_size in (1, 7, 128, PRODUCTION_CHUNK_SIZE):
        chunking(chunk_size, 1)
        roots.add(compute_checksum_localfs(str(folder), algorithm).content_digest)

    assert len(roots) == 1


# ── Discrimination: invariance must not have become insensitivity ─────────────


@algorithms
@pytest.mark.parametrize("position", [0, 99, 100, 500, 999])
def test_one_flipped_byte_changes_the_digest_at_every_chunk_position(
    hashed, algorithm, position
):
    """Flips land at a chunk start, a chunk end and mid-chunk, so a boundary
    bug that dropped or double-counted bytes cannot pass."""
    flipped = bytearray(BODY)
    flipped[position] ^= 0xFF

    assert (
        hashed(algorithm, 100, 7, bytes(flipped)).content_digest
        != hashed(algorithm, 100, 7).content_digest
    )


@algorithms
def test_reordering_the_bytes_changes_the_digest(hashed, algorithm):
    """Rules out any combiner that is order-insensitive over chunks."""
    swapped = BODY[100:200] + BODY[:100] + BODY[200:]

    assert (
        hashed(algorithm, 100, 1, swapped).content_digest
        != hashed(algorithm, 100, 1).content_digest
    )
    assert (
        hashed(algorithm, 100, 1, swapped).merkle_root
        != hashed(algorithm, 100, 1).merkle_root
    )


@algorithms
def test_a_truncated_file_does_not_keep_the_original_digest(hashed, algorithm):
    assert (
        hashed(algorithm, 100, 1, BODY[:-1]).content_digest
        != hashed(algorithm, 100, 1).content_digest
    )
