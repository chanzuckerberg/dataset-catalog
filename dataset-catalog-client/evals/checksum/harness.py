"""
Core plumbing for the checksum eval: tiers, checks, context, runner.

A *check* is one comparison with a recorded outcome. Dimensions yield checks
rather than asserting, so a failure never aborts the run — the point of an eval
is the full picture, not the first stop.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from catalog_client.utils.checksum import hashing
from catalog_client.utils.checksum.algorithm import Algorithm, new_hasher


class Tier(StrEnum):
    """
    How expensive a check is, and therefore when it runs.

    fast  seconds, <=16MB of temp files, no credentials — safe in CI
    full  minutes, crosses the production 256MB CHUNK_SIZE, up to 1GB on disk
    aws   talks to a real S3 bucket; opt-in only, never pulled in by the others
    """

    fast = "fast"
    full = "full"
    aws = "aws"


def tier_includes(requested: Tier, check_tier: Tier) -> bool:
    """
    Whether a check of `check_tier` runs when `requested` was asked for.

    full implies fast, because the cheap correctness checks are the baseline any
    expensive run should also satisfy. aws is deliberately NOT implied by full:
    it costs money and needs credentials, so it is only ever explicit.
    """
    if check_tier == Tier.aws or requested == Tier.aws:
        return check_tier == requested
    return requested == Tier.full or check_tier == Tier.fast


class Status(StrEnum):
    passed = "pass"
    failed = "fail"
    skipped = "skip"
    errored = "error"


@dataclass
class Check:
    """One recorded outcome. `metrics` carries numbers worth trending."""

    id: str
    dimension: str
    tier: Tier
    status: Status
    message: str = ""
    metrics: dict[str, float | int | str] = field(default_factory=dict)

    @property
    def counts_against_us(self) -> bool:
        return self.status in (Status.failed, Status.errored)


def compare(
    check_id: str,
    dimension: str,
    tier: Tier,
    actual: object,
    expected: object,
    note: str = "",
    **metrics: float | int | str,
) -> Check:
    """A check that passes when actual == expected, reporting both when not."""
    ok = actual == expected
    message = "" if ok else f"expected {expected!r}, got {actual!r}"
    if note:
        message = f"{note}: {message}" if message else note
    return Check(
        id=check_id,
        dimension=dimension,
        tier=tier,
        status=Status.passed if ok else Status.failed,
        message=message,
        metrics=dict(metrics),
    )


def assert_that(
    check_id: str,
    dimension: str,
    tier: Tier,
    ok: bool,
    message: str = "",
    **metrics: float | int | str,
) -> Check:
    """A check from a boolean the caller already evaluated."""
    return Check(
        id=check_id,
        dimension=dimension,
        tier=tier,
        status=Status.passed if ok else Status.failed,
        message="" if ok else message,
        metrics=dict(metrics),
    )


def skip(check_id: str, dimension: str, tier: Tier, why: str) -> Check:
    return Check(
        id=check_id, dimension=dimension, tier=tier, status=Status.skipped, message=why
    )


@dataclass
class Thresholds:
    """
    Gates for the measured (non-boolean) dimensions.

    Deliberately loose: these exist to catch an order-of-magnitude regression —
    a hasher that starts buffering whole chunks, or one that drops to a tenth of
    its throughput — not to police normal machine-to-machine variance.
    """

    min_throughput_mb_s: float = 20.0
    # Peak RSS *above the interpreter baseline* while hashing. hashing.py claims
    # peak usage is one READ_BUFFER (64KB) regardless of file size; 96MB leaves
    # room for allocator slack and the boto/blake3 extension modules while still
    # failing loudly if a 256MB chunk is ever held in memory.
    max_peak_rss_bytes: int = 96 * 1024 * 1024
    fuzz_cases: int = 24


@dataclass
class Context:
    """Everything a dimension needs to run. Passed to every `run(ctx)`."""

    tier: Tier
    workdir: Path
    seed: str = "catalog-checksum-eval"
    update_golden: bool = False
    s3_bucket: str | None = None
    s3_prefix: str = "catalog-checksum-eval"
    keep_s3_objects: bool = False
    thresholds: Thresholds = field(default_factory=Thresholds)

    def wants(self, check_tier: Tier) -> bool:
        return tier_includes(self.tier, check_tier)

    def scratch(self, name: str) -> Path:
        path = self.workdir / name
        path.mkdir(parents=True, exist_ok=True)
        return path


def available_algorithms() -> list[Algorithm]:
    """
    The algorithms this install can actually run.

    blake3, crc64 and crc64nvme live in the optional `checksum` extra and raise
    ImportError from new_hasher when absent. An eval that silently reported a
    pass for an algorithm it never ran would be worse than one that skips it, so
    availability is probed once, up front.
    """
    usable = []
    for algorithm in Algorithm:
        try:
            new_hasher(algorithm)
        except ImportError:
            continue
        usable.append(algorithm)
    return usable


@contextmanager
def chunking(chunk_size: int, read_buffer: int) -> Iterator[None]:
    """
    Temporarily change the chunk size and read buffer.

    Patched on `hashing`, not `models`: hashing.py binds CHUNK_SIZE by value at
    import, so patching models.CHUNK_SIZE has no effect (same reason the unit
    suite patches it there).
    """
    original_chunk, original_buffer = hashing.CHUNK_SIZE, hashing.READ_BUFFER
    hashing.CHUNK_SIZE, hashing.READ_BUFFER = chunk_size, read_buffer
    try:
        yield
    finally:
        hashing.CHUNK_SIZE, hashing.READ_BUFFER = original_chunk, original_buffer


@dataclass
class DimensionRun:
    name: str
    checks: list[Check]
    seconds: float


def run_dimension(
    name: str, runner: Callable[[Context], Iterator[Check]], ctx: Context
) -> DimensionRun:
    """
    Run one dimension, converting an unexpected exception into an errored check.

    A dimension that blows up mid-way keeps the checks it already yielded: they
    are real results, and discarding them would hide which case broke it.
    """
    checks: list[Check] = []
    started = time.perf_counter()
    try:
        for check in runner(ctx):
            checks.append(check)
    except Exception as exc:
        checks.append(
            Check(
                id=f"{name}.dimension_crashed",
                dimension=name,
                tier=ctx.tier,
                status=Status.errored,
                message=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            )
        )
    return DimensionRun(name=name, checks=checks, seconds=time.perf_counter() - started)
