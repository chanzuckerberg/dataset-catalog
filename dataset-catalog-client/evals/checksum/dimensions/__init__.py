"""
The dimension registry.

Each dimension is a module exposing `NAME` and `run(ctx) -> Iterator[Check]`, and
is registered here with the cheapest tier it can run at. Ordered cheapest-first
so a broken build fails on conformance before spending minutes in scale.

The tier lives here rather than inside each `run()` so that `run_dimension` can
enforce it for every dimension at once — a dimension cannot be registered without
declaring what it costs, and so cannot forget to honour it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from evals.checksum.dimensions import (
    aws_native,
    conformance,
    golden,
    invariance,
    scale,
    sizes,
)
from evals.checksum.harness import Check, Context, Tier

Runner = Callable[[Context], Iterator[Check]]


@dataclass(frozen=True)
class Dimension:
    """
    One registered dimension.

    needs  the cheapest tier that runs it; `run_dimension` skips it below that
    why    the skip message, phrased for someone who asked for a cheaper tier
    """

    name: str
    run: Runner
    description: str
    needs: Tier = Tier.fast
    why: str = "not run at this tier"


DIMENSIONS: dict[str, Dimension] = {
    dimension.name: dimension
    for dimension in (
        Dimension(
            conformance.NAME,
            conformance.run,
            "digests vs independent one-shot implementations",
            why="correctness checks are not run at --tier aws",
        ),
        Dimension(
            golden.NAME,
            golden.run,
            "digests vs committed golden vectors",
            why="vector comparison is not run at --tier aws",
        ),
        Dimension(
            invariance.NAME,
            invariance.run,
            "seeded fuzzing of stability, partitioning and sensitivity",
            why="fuzzing is not run at --tier aws",
        ),
        Dimension(
            sizes.NAME,
            sizes.run,
            "total_size vs os.stat/os.walk, including sparse and linked files",
            why="size checks are not run at --tier aws",
        ),
        Dimension(
            scale.NAME,
            scale.run,
            "production 256MB chunking, throughput and peak RSS (full tier)",
            needs=Tier.full,
            why="scale checks need --tier full (up to 1GB)",
        ),
        Dimension(
            aws_native.NAME,
            aws_native.run,
            "conformance against real S3, not moto (aws tier)",
            needs=Tier.aws,
            why="real-S3 checks need --tier aws",
        ),
    )
}

__all__ = ["DIMENSIONS", "Dimension", "Runner"]
