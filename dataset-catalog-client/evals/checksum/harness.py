"""
Core plumbing for the checksum eval: tiers, checks, context, runner.

A *check* is one comparison with a recorded outcome. Dimensions yield checks
rather than asserting, so a failure never aborts the run — the point of an eval
is the full picture, not the first stop.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from catalog_client.utils.checksum import hashing
from catalog_client.utils.checksum.algorithm import Algorithm, new_hasher

if TYPE_CHECKING:  # imported for typing only; dimensions imports this module
    from evals.checksum.dimensions import Dimension


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

    PARALLEL_READ_BUFFER is patched to the same value. It is a separate
    constant only so that pooled reads can use a larger buffer than serial
    ones; a configuration under test must apply to both, or a check that runs
    through a pool would silently keep the production buffer.
    """
    original = (hashing.CHUNK_SIZE, hashing.READ_BUFFER, hashing.PARALLEL_READ_BUFFER)
    hashing.CHUNK_SIZE = chunk_size
    hashing.READ_BUFFER = hashing.PARALLEL_READ_BUFFER = read_buffer
    try:
        yield
    finally:
        (
            hashing.CHUNK_SIZE,
            hashing.READ_BUFFER,
            hashing.PARALLEL_READ_BUFFER,
        ) = original


@dataclass
class DimensionRun:
    name: str
    checks: list[Check]
    seconds: float


def run_dimension(dimension: Dimension, ctx: Context) -> DimensionRun:
    """
    Run one dimension, enforcing its tier and containing its failures.

    The tier is enforced here rather than inside each `run()` because a dimension
    that forgets to check it does not fail — it quietly runs at a tier that never
    asked for it (checks tagged `Tier.fast` still execute under `--tier aws`) and
    reports a healthy pass count. Declaring `needs` in the registry makes that
    unforgettable: a dimension cannot be registered without stating its tier, and
    the skip is emitted from one place for all of them.

    A dimension that blows up mid-way keeps the checks it already yielded: they
    are real results, and discarding them would hide which case broke it.
    """
    name = dimension.name
    started = time.perf_counter()

    if not ctx.wants(dimension.needs):
        return DimensionRun(
            name=name,
            checks=[skip(f"{name}.all", name, dimension.needs, dimension.why)],
            seconds=time.perf_counter() - started,
        )

    checks: list[Check] = []
    try:
        for check in dimension.run(ctx):
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
    if not checks:
        # Zero checks is never a legitimate outcome: a dimension the tier declines
        # never gets here, and one that runs has something to say. Reaching here
        # means a corpus filtered down to nothing or an early return, and the
        # report would have shown a clean "ok" over an empty list — the one
        # failure mode an eval must not have.
        checks.append(
            Check(
                id=f"{name}.produced_no_checks",
                dimension=name,
                tier=ctx.tier,
                status=Status.errored,
                message=(
                    "the dimension ran at this tier and yielded no checks at all; "
                    "a case list filtered down to nothing, or an early return"
                ),
            )
        )
    return DimensionRun(name=name, checks=checks, seconds=time.perf_counter() - started)
