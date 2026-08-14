"""
The dimension registry.

Each dimension is a module exposing `NAME` and `run(ctx) -> Iterator[Check]`.
Ordered cheapest-first so a broken build fails on conformance before spending
minutes in scale.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from evals.checksum.dimensions import (
    aws_native,
    conformance,
    golden,
    invariance,
    scale,
    sizes,
)
from evals.checksum.harness import Check, Context

Runner = Callable[[Context], Iterator[Check]]

DIMENSIONS: dict[str, Runner] = {
    conformance.NAME: conformance.run,
    golden.NAME: golden.run,
    invariance.NAME: invariance.run,
    sizes.NAME: sizes.run,
    scale.NAME: scale.run,
    aws_native.NAME: aws_native.run,
}

DESCRIPTIONS: dict[str, str] = {
    conformance.NAME: "digests vs independent one-shot implementations",
    golden.NAME: "digests vs committed golden vectors",
    invariance.NAME: "seeded fuzzing of stability, partitioning and sensitivity",
    sizes.NAME: "total_size vs os.stat/os.walk, including sparse and linked files",
    scale.NAME: "production 256MB chunking, throughput and peak RSS (full tier)",
    aws_native.NAME: "conformance against real S3, not moto (aws tier)",
}

__all__ = ["DIMENSIONS", "DESCRIPTIONS", "Runner"]
