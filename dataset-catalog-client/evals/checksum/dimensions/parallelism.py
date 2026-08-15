"""
Does concurrency move a digest?

Hashing a local tree fans out across a thread pool, so the order files finish
in varies from run to run. The order their digests are *combined* in must not:
`_directory_result` hashes each child's name and digest in insertion order, so
a walk that inserted two siblings the other way round produces a different
folder digest from identical bytes.

`conformance` and `golden` cannot catch that. Both run whatever the walk
produces, so a walk that reordered children would simply have its new value
pinned. Only comparing the walk against *itself at a different worker count*
distinguishes "this is the digest" from "this is the digest today".

Two things are varied, because each could break a digest on its own:

  worker count   2 and 3 divide none of the corpus trees evenly, so work
                 distributes unevenly and completion order genuinely differs
  read buffer    pooled reads use a larger buffer than serial ones, which is
                 sound only because buffer size is not a digest input; the
                 pooled runs here exercise that

The pool gate is forced open rather than fed a large fixture. It is a
performance heuristic keyed on mean file size, and every corpus tree is far
below it — left alone, this dimension would compare the serial path against
itself and pass forever. Forcing it costs nothing and exercises the concurrent
walk across every tree shape rather than one synthetic large one. Whether the
gate opens at the right size is a throughput question, tested in
tests/utils/checksum/test_hashing.py, not a digest one.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from catalog_client.utils.checksum import hashing
from catalog_client.utils.checksum.algorithm import Algorithm
from catalog_client.utils.checksum.hashing import (
    ChecksumResult,
    compute_checksum_localfs,
)
from evals.checksum import corpus
from evals.checksum.corpus import cases_for
from evals.checksum.harness import Check, Context, Tier, compare

NAME = "parallelism"

# Deliberately not divisors of any corpus tree's file count, so no worker count
# lands on a tidy split. 1 is the baseline everything is measured against.
WORKER_COUNTS = (2, 3, 8)

# Deeper than the recursive walk this replaced was comfortable with. Breadth
# first specifically so nesting does not consume Python stack.
_CHAIN_DEPTH = 200


@contextmanager
def _pool_forced() -> Iterator[None]:
    """Lower the pool gate so any tree takes the concurrent path."""
    original = (hashing.PARALLEL_MIN_MEAN_BYTES, hashing._MIN_FILES_FOR_POOL)
    hashing.PARALLEL_MIN_MEAN_BYTES = 0
    hashing._MIN_FILES_FOR_POOL = 0
    try:
        yield
    finally:
        (
            hashing.PARALLEL_MIN_MEAN_BYTES,
            hashing._MIN_FILES_FOR_POOL,
        ) = original


def _digest_map(node: ChecksumResult, prefix: str = "") -> dict[str, str]:
    """
    Every digest in a tree, keyed by relative path.

    Comparing roots alone would pass if two children swapped digests and the
    parent happened to collide. It also localises a failure to a path rather
    than reporting only that the root moved.
    """
    flat = {prefix or ".": node.content_digest}
    for name, child in node.children.items():
        flat.update(_digest_map(child, f"{prefix}{name}/"))
    return flat


def _deep_chain(workdir: Path) -> Path:
    root = workdir / "deep_chain"
    # Single-character segments: numbered ones would push the total path past
    # the OS limit long before the depth became interesting.
    leaf = root.joinpath(*("d" * _CHAIN_DEPTH))
    corpus.write(leaf / "leaf.bin", "parallelism:deep_chain", 32)
    return root


def _trees(ctx: Context) -> Iterator[tuple[str, Path]]:
    workdir = ctx.scratch(NAME)
    _, tree_cases = cases_for(ctx.tier)
    for case in tree_cases:
        yield case.name, case.materialise(workdir)
    yield "deep_chain", _deep_chain(workdir)


def run(ctx: Context) -> Iterator[Check]:
    from evals.checksum.harness import available_algorithms

    for name, root in _trees(ctx):
        for algorithm in available_algorithms():
            yield from _one_tree(name, root, algorithm)


def _one_tree(name: str, root: Path, algorithm: Algorithm) -> Iterator[Check]:
    # The baseline is the serial walk under the natural gate: the code path
    # that predates the pool, and the one golden.json pins.
    serial = compute_checksum_localfs(str(root), algorithm, max_workers=1)
    baseline = _digest_map(serial)

    for workers in WORKER_COUNTS:
        case = f"{NAME}.{name}.{algorithm.value}.w{workers}"
        with _pool_forced():
            actual = compute_checksum_localfs(str(root), algorithm, max_workers=workers)
        yield compare(
            f"{case}.content_digest",
            NAME,
            Tier.fast,
            actual.content_digest,
            serial.content_digest,
            note="a folder digest changed with worker count",
        )
        yield compare(
            f"{case}.total_size",
            NAME,
            Tier.fast,
            actual.total_size,
            serial.total_size,
        )
        yield compare(
            f"{case}.every_descendant",
            NAME,
            Tier.fast,
            _digest_map(actual),
            baseline,
            note="a descendant digest changed with worker count",
        )
