"""
Does our digest equal the one an independent implementation produces?

The unit suite pins each algorithm to a single published check value
(`CRC64("123456789")`). That proves the polynomial is right; it says nothing
about the streaming path that actually produces asset checksums. Here every
corpus body goes through both our streaming/chunking machinery and a one-shot
oracle, and the two must agree exactly.

Also checked here, because they are cheap and they are what consumers rely on:
digest width, and that `s3_base64` is a faithful re-encoding of `file_hash`
rather than a separate computation that could drift from it.
"""

from __future__ import annotations

import base64
import shutil
from collections.abc import Iterator

from catalog_client.utils.checksum.algorithm import DIGEST_HEX_LENGTH
from catalog_client.utils.checksum.hashing import (
    compute_checksum,
    compute_checksum_localfs,
)
from evals.checksum import oracles
from evals.checksum.corpus import cases_for
from evals.checksum.harness import Check, Context, Tier, assert_that, compare, gate

NAME = "conformance"


def run(ctx: Context) -> Iterator[Check]:
    from evals.checksum.harness import available_algorithms

    declined = gate(NAME, ctx, Tier.fast)
    if declined:
        yield declined
        return

    algorithms = available_algorithms()
    file_cases, tree_cases = cases_for(ctx.tier)
    workdir = ctx.scratch("conformance")

    for case in file_cases:
        directory = workdir / case.name
        directory.mkdir(parents=True, exist_ok=True)
        path = case.materialise(directory)
        try:
            # One materialisation, every algorithm — at 256MB a case costs real
            # I/O, and re-writing it per algorithm would triple the full tier.
            for algorithm in algorithms:
                expected = oracles.digest(path, algorithm)
                result = compute_checksum_localfs(str(path), algorithm)
                prefix = f"{NAME}.{algorithm.value}.{case.name}"

                yield compare(
                    f"{prefix}.content_digest",
                    NAME,
                    case.tier,
                    result.content_digest,
                    expected,
                    note=case.why,
                    size_bytes=case.size,
                )
                yield compare(
                    f"{prefix}.digest_width",
                    NAME,
                    case.tier,
                    len(result.content_digest),
                    DIGEST_HEX_LENGTH[algorithm],
                )
                yield compare(
                    f"{prefix}.s3_base64_round_trip",
                    NAME,
                    case.tier,
                    base64.b64decode(result.s3_base64).hex(),
                    result.file_hash,
                    note="the base64 S3 receives must decode back to file_hash",
                )
                # compute_checksum is the documented entry point; a router that
                # diverged from the local implementation would be invisible to
                # every other check here.
                yield compare(
                    f"{prefix}.router_agrees",
                    NAME,
                    case.tier,
                    compute_checksum(str(path), algorithm).content_digest,
                    result.content_digest,
                )
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    for tree in tree_cases:
        directory = workdir / f"tree_{tree.name}"
        directory.mkdir(parents=True, exist_ok=True)
        root = tree.materialise(directory)
        try:
            for algorithm in algorithms:
                result = compute_checksum_localfs(str(root), algorithm)
                prefix = f"{NAME}.{algorithm.value}.tree_{tree.name}"

                yield assert_that(
                    f"{prefix}.is_directory",
                    NAME,
                    tree.tier,
                    result.is_directory,
                    "a directory result must be flagged as one",
                )
                # A folder digest has no external oracle — it is our own scheme.
                # What is checkable without one: every child's digest is the
                # oracle's digest, so the only unverified step is the
                # combination, which golden.py pins.
                for name, child in result.children.items():
                    if child.is_directory:
                        continue
                    yield compare(
                        f"{prefix}.child.{name}",
                        NAME,
                        tree.tier,
                        child.content_digest,
                        oracles.digest(root / name, algorithm),
                        note="a folder child must hash exactly as it would alone",
                    )
                yield compare(
                    f"{prefix}.child_order",
                    NAME,
                    tree.tier,
                    list(result.children),
                    sorted(result.children),
                    note="children must be combined in name order, not listing order",
                )
        finally:
            shutil.rmtree(directory, ignore_errors=True)
