"""
Does it hold up at production settings and production sizes?

Two claims in the source have no test behind them, because testing them needs
files the unit suite cannot afford to create:

  1. Chunking works at CHUNK_SIZE = 256MB. Every chunking test shrinks the
     constant, so the manifest, the composite, and the two-hasher read loop have
     only ever been observed at toy sizes. A 256MB-specific arithmetic mistake
     (an int overflow, a boundary that only misfires above some threshold) would
     ship green.

  2. "no chunk is ever held in memory: peak usage is one buffer per stream in
     flight, regardless of CHUNK_SIZE" (hashing.py). That is a comment. Here it
     is a measurement: a child process hashes a 1GB *file* and reports peak RSS
     above its own baseline, which must stay far below the file size. A single
     file never engages the thread pool, so this stays a statement about chunk
     buffering rather than about worker count.

Throughput is recorded per algorithm — useful as a trend line, and gated only
loosely, since eval machines vary far more than the code does.

Everything in this module is full tier: it generates up to 1GB of temp files.
Each fixture is deleted as soon as its checks are done, so the disk high-water
mark is one file, not the whole corpus.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

from catalog_client.utils.checksum.hashing import compute_checksum_localfs
from evals.checksum import corpus, oracles
from evals.checksum.corpus import CHUNK_SIZE, READ_BUFFER
from evals.checksum.harness import (
    Check,
    Context,
    Status,
    Tier,
    assert_that,
    compare,
)

NAME = "scale"

# One byte over three chunks: exercises full chunks, a ragged final chunk, and
# a size that no 32-bit accumulator survives untested.
THROUGHPUT_SIZE = 3 * CHUNK_SIZE + 1  # 768MB + 1
MEMORY_SIZE = 1024 * 1024 * 1024  # 1GB

_MB = 1024 * 1024


def _probe(path: Path, algorithm) -> dict:
    """Hash in a child process so peak RSS is attributable to the hashing."""
    completed = subprocess.run(
        [sys.executable, "-m", "evals.checksum._probe", str(path), algorithm.value],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def run(ctx: Context) -> Iterator[Check]:
    from evals.checksum.harness import available_algorithms

    algorithms = available_algorithms()
    workdir = ctx.scratch("scale")

    yield from _multi_chunk(ctx, workdir, algorithms)
    yield from _memory_ceiling(ctx, workdir, algorithms)
    shutil.rmtree(workdir, ignore_errors=True)


def _multi_chunk(ctx: Context, workdir: Path, algorithms) -> Iterator[Check]:
    """A body spanning several real 256MB chunks, at untouched production constants."""
    path = workdir / "multi_chunk.bin"
    generated = time.perf_counter()
    corpus.write(path, "scale/multi_chunk", THROUGHPUT_SIZE)
    yield Check(
        id=f"{NAME}.fixture_generated",
        dimension=NAME,
        tier=Tier.full,
        status=Status.skipped,
        message=f"generated {THROUGHPUT_SIZE / _MB:.0f}MB fixture",
        metrics={"seconds": round(time.perf_counter() - generated, 2)},
    )

    try:
        for algorithm in algorithms:
            started = time.perf_counter()
            result = compute_checksum_localfs(str(path), algorithm)
            elapsed = time.perf_counter() - started
            throughput = (THROUGHPUT_SIZE / _MB) / elapsed if elapsed else 0.0
            prefix = f"{NAME}.{algorithm.value}"

            yield compare(
                f"{prefix}.digest_at_production_chunk_size",
                NAME,
                Tier.full,
                result.content_digest,
                oracles.digest(path, algorithm),
                note="a multi-chunk body must still match the one-shot oracle",
                size_bytes=THROUGHPUT_SIZE,
                throughput_mb_s=round(throughput, 1),
                seconds=round(elapsed, 2),
            )
            # 3 * CHUNK_SIZE + 1 must be exactly four chunks, the last holding
            # a single byte.
            yield compare(
                f"{prefix}.chunk_count",
                NAME,
                Tier.full,
                len(result.chunks),
                4,
                note="768MB + 1 at a 256MB chunk size is four chunks",
            )
            yield compare(
                f"{prefix}.final_chunk_size",
                NAME,
                Tier.full,
                result.chunks[-1].size,
                1,
                note="the ragged tail chunk must hold exactly the leftover byte",
            )
            yield assert_that(
                f"{prefix}.manifest_tiles_exactly",
                NAME,
                Tier.full,
                sum(chunk.size for chunk in result.chunks) == THROUGHPUT_SIZE
                and [chunk.offset for chunk in result.chunks]
                == [0, CHUNK_SIZE, 2 * CHUNK_SIZE, 3 * CHUNK_SIZE],
                f"unexpected manifest: {[(c.offset, c.size) for c in result.chunks]}",
            )
            yield assert_that(
                f"{prefix}.composite_differs_from_whole",
                NAME,
                Tier.full,
                result.merkle_root != result.file_hash,
                "with four chunks the composite must not equal the whole-object hash",
            )
            yield assert_that(
                f"{prefix}.throughput",
                NAME,
                Tier.full,
                throughput >= ctx.thresholds.min_throughput_mb_s,
                f"{throughput:.1f} MB/s is below the "
                f"{ctx.thresholds.min_throughput_mb_s} MB/s floor",
                throughput_mb_s=round(throughput, 1),
            )
    finally:
        path.unlink(missing_ok=True)


def _memory_ceiling(ctx: Context, workdir: Path, algorithms) -> Iterator[Check]:
    """Hash 1GB in a child process and hold peak RSS to the stated ceiling."""
    path = workdir / "memory.bin"
    corpus.write(path, "scale/memory", MEMORY_SIZE)

    try:
        for algorithm in algorithms:
            measured = _probe(path, algorithm)
            peak = measured["peak_rss_delta_bytes"]
            prefix = f"{NAME}.{algorithm.value}.memory"

            yield assert_that(
                f"{prefix}.peak_rss",
                NAME,
                Tier.full,
                peak <= ctx.thresholds.max_peak_rss_bytes,
                f"hashing {MEMORY_SIZE / _MB:.0f}MB grew RSS by {peak / _MB:.1f}MB, "
                f"ceiling is {ctx.thresholds.max_peak_rss_bytes / _MB:.0f}MB — "
                "a chunk is probably being buffered",
                peak_rss_mb=round(peak / _MB, 1),
                baseline_rss_mb=round(measured["baseline_rss_bytes"] / _MB, 1),
                throughput_mb_s=round(
                    (MEMORY_SIZE / _MB) / measured["seconds"]
                    if measured["seconds"]
                    else 0.0,
                    1,
                ),
            )
            # A memory measurement is only meaningful if the hash was right.
            yield compare(
                f"{prefix}.digest",
                NAME,
                Tier.full,
                measured["content_digest"],
                oracles.digest(path, algorithm),
                note="1GB digest must match the one-shot oracle",
            )
            yield compare(
                f"{prefix}.chunk_count",
                NAME,
                Tier.full,
                measured["chunk_count"],
                4,
                note=f"1GB at a {CHUNK_SIZE / _MB:.0f}MB chunk size is four chunks",
            )
            yield compare(
                f"{prefix}.total_size",
                NAME,
                Tier.full,
                measured["total_size"],
                MEMORY_SIZE,
                note="a 1GB size must survive the round trip intact",
            )
    finally:
        path.unlink(missing_ok=True)

    yield Check(
        id=f"{NAME}.constants",
        dimension=NAME,
        tier=Tier.full,
        status=Status.skipped,
        message=(
            f"measured at CHUNK_SIZE={CHUNK_SIZE} READ_BUFFER={READ_BUFFER} "
            "(production values, unpatched)"
        ),
        metrics={"chunk_size": CHUNK_SIZE, "read_buffer": READ_BUFFER},
    )
