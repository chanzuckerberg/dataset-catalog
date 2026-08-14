"""
Randomised probing of the properties the checksums exist for.

The unit suite checks these properties at hand-picked sizes and chunk sizes.
Hand-picked cases test the boundaries the author thought of; this dimension
draws (size, chunk_size, read_buffer) triples from a seeded generator so the
combinations nobody thought of get covered over repeated runs.

Three properties, each of which would break something real if violated:

  stability     content_digest does not depend on how the bytes were read.
                Violating it means the same file gets two different catalog
                checksums depending on chunk settings.
  partitioning  merkle_root is stable while the read buffer divides the chunk,
                and describes the partition otherwise. It is the S3 composite.
  sensitivity   any change to the bytes changes the digest. Without this a
                checksum cannot detect corruption, which is its only job.

The seed is reported with every check, so a failure is replayable with
`--seed <value>`.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from pathlib import Path

from catalog_client.utils.checksum.algorithm import Algorithm
from catalog_client.utils.checksum.hashing import compute_checksum_localfs
from evals.checksum import corpus
from evals.checksum.harness import (
    Check,
    Context,
    Tier,
    assert_that,
    chunking,
    compare,
    gate,
)

NAME = "invariance"

# CRCs are linear, so a byte transposition is not guaranteed to change a short
# CRC the way a cryptographic hash is. Reordering is therefore only asserted
# where it is a genuine guarantee; flips and truncations are asserted for all.
_REORDER_SAFE = (
    Algorithm.blake3,
    Algorithm.blake2b,
    Algorithm.crc64,
    Algorithm.crc64nvme,
)

_SIZES = (1, 2, 63, 1024, 4095, 4096, 4097, 65536, 70_001, 262_144)
_CHUNKS = (512, 1024, 4096, 16_384, 65_536)
_BUFFERS = (1, 7, 64, 512, 1024, 4096, 16_384)


def _write(path: Path, body: bytes) -> str:
    path.write_bytes(body)
    return str(path)


def _digest(path: str, algorithm: Algorithm, chunk_size: int, read_buffer: int):
    with chunking(chunk_size, read_buffer):
        return compute_checksum_localfs(path, algorithm)


def run(ctx: Context) -> Iterator[Check]:
    from evals.checksum.harness import available_algorithms

    declined = gate(NAME, ctx, Tier.fast)
    if declined:
        yield declined
        return

    algorithms = available_algorithms()
    rng = random.Random(ctx.seed)
    workdir = ctx.scratch("invariance")
    scratch = workdir / "body.bin"
    seed_note = f"seed={ctx.seed}"

    for index in range(ctx.thresholds.fuzz_cases):
        size = rng.choice(_SIZES)
        chunk_size = rng.choice(_CHUNKS)
        read_buffer = rng.choice(_BUFFERS)
        algorithm = rng.choice(algorithms)
        body = corpus.content(f"{ctx.seed}/fuzz/{index}", size)
        path = _write(scratch, body)
        case = f"{index:02d}.{algorithm.value}.size{size}"

        baseline = _digest(path, algorithm, corpus.CHUNK_SIZE, corpus.READ_BUFFER)
        varied = _digest(path, algorithm, chunk_size, read_buffer)

        yield compare(
            f"{NAME}.stability.{case}.chunk{chunk_size}_buf{read_buffer}",
            NAME,
            Tier.fast,
            varied.content_digest,
            baseline.content_digest,
            note=f"content_digest must not depend on partitioning ({seed_note})",
            size_bytes=size,
        )

        # The manifest must tile the body exactly regardless of how it was read:
        # a gap or an overlap here would mean a chunk's bytes were hashed twice
        # or not at all.
        offsets = [(chunk.offset, chunk.size) for chunk in varied.chunks]
        yield assert_that(
            f"{NAME}.tiling.{case}.chunk{chunk_size}_buf{read_buffer}",
            NAME,
            Tier.fast,
            sum(length for _, length in offsets) == size
            and all(
                offset == sum(length for _, length in offsets[:position])
                for position, (offset, _) in enumerate(offsets)
            ),
            f"manifest does not tile {size} bytes exactly: {offsets} ({seed_note})",
            chunks=len(offsets),
        )

        # merkle_root is partition-dependent by design, but only on the chunk
        # size. Two read buffers that both divide the chunk must agree.
        if chunk_size % read_buffer == 0:
            divisor = max(
                candidate
                for candidate in _BUFFERS
                if chunk_size % candidate == 0 and candidate != read_buffer
            )
            other = _digest(path, algorithm, chunk_size, divisor)
            yield compare(
                f"{NAME}.partitioning.{case}.chunk{chunk_size}",
                NAME,
                Tier.fast,
                varied.merkle_root,
                other.merkle_root,
                note=(
                    f"merkle_root must be stable while the buffer divides the "
                    f"chunk (buffers {read_buffer} vs {divisor}, {seed_note})"
                ),
            )

        if size == 0:
            continue

        position = rng.randrange(size)
        flipped = bytearray(body)
        flipped[position] ^= 0xFF
        yield assert_that(
            f"{NAME}.sensitivity.flip.{case}",
            NAME,
            Tier.fast,
            _digest(
                _write(scratch, bytes(flipped)), algorithm, chunk_size, read_buffer
            ).content_digest
            != varied.content_digest,
            f"flipping byte {position} of {size} did not change the digest ({seed_note})",
        )

        yield assert_that(
            f"{NAME}.sensitivity.truncate.{case}",
            NAME,
            Tier.fast,
            _digest(
                _write(scratch, body[:-1]), algorithm, chunk_size, read_buffer
            ).content_digest
            != varied.content_digest,
            f"dropping the last of {size} bytes did not change the digest ({seed_note})",
        )

        if size >= 2 and algorithm in _REORDER_SAFE:
            left = rng.randrange(size)
            right = rng.randrange(size)
            if body[left] != body[right]:
                swapped = bytearray(body)
                swapped[left], swapped[right] = swapped[right], swapped[left]
                yield assert_that(
                    f"{NAME}.sensitivity.reorder.{case}",
                    NAME,
                    Tier.fast,
                    _digest(
                        _write(scratch, bytes(swapped)),
                        algorithm,
                        chunk_size,
                        read_buffer,
                    ).content_digest
                    != varied.content_digest,
                    f"swapping bytes {left} and {right} kept the digest ({seed_note})",
                )

    # A file's digest must be the same whether it is hashed alone or reached as
    # a folder child — the promise that makes a stored S3 checksum and a
    # computed one interchangeable inside a folder root.
    for index in range(4):
        size = rng.choice(_SIZES)
        chunk_size = rng.choice(_CHUNKS)
        body = corpus.content(f"{ctx.seed}/child/{index}", size)
        folder = workdir / f"folder{index}"
        (folder / "nested").mkdir(parents=True, exist_ok=True)
        (folder / "nested" / "child.bin").write_bytes(body)
        standalone = _write(workdir / f"alone{index}.bin", body)

        with chunking(chunk_size, corpus.READ_BUFFER):
            tree = compute_checksum_localfs(str(folder), algorithms[0])
            alone = compute_checksum_localfs(standalone, algorithms[0])

        yield compare(
            f"{NAME}.child_identity.{index}.size{size}.chunk{chunk_size}",
            NAME,
            Tier.fast,
            tree.children["nested"].children["child.bin"].content_digest,
            alone.content_digest,
            note=f"a nested child must hash as it would standalone ({seed_note})",
        )
