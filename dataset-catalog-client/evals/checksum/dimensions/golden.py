"""
Are the digests we produce today the digests we produced before?

This is the gap no self-consistency test can close. Every invariance and
reproducibility test in the unit suite compares our output to our own output, so
a change to the Merkle scheme — a different child separator, a different raw
packing, a reordering — keeps all of them green while silently invalidating
every checksum already written into the catalog.

The vectors in vectors/golden.json are that missing anchor: values committed to
git, regenerated only by an explicit `--update-golden`. A diff on that file in a
pull request is exactly the "this changes stored digests" signal a reviewer
needs, and it is the reason the eval pins merkle_root and chunk_count too, not
just the content_digest an asset carries.

Cases are recorded per (case, chunk_size, read_buffer) because merkle_root is
deliberately partition-dependent. Small-chunk configurations are included so
multi-chunk composites are pinned without needing a 256MB fixture.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

from catalog_client.utils.checksum.algorithm import Algorithm
from catalog_client.utils.checksum.hashing import compute_checksum_localfs
from evals.checksum.corpus import (
    CHUNK_SIZE,
    FILE_CASES,
    READ_BUFFER,
    TREE_CASES,
    cases_for,
)
from evals.checksum.harness import (
    PRODUCTION_CHUNK_SIZE,
    PRODUCTION_READ_BUFFER,
    Check,
    Context,
    Status,
    Tier,
    assert_that,
    chunking,
    compare,
    gate,
    skip,
)

NAME = "golden"

VECTORS = Path(__file__).resolve().parent.parent / "vectors" / "golden.json"

# (chunk_size, read_buffer) configurations to pin.
#   production  what a real caller gets
#   4KB/1KB     several chunks over a small body, so merkle_root is exercised
#   64KB/4KB    a chunk that is an exact multiple of the buffer
CONFIGS: tuple[tuple[int, int], ...] = (
    (CHUNK_SIZE, READ_BUFFER),
    (4096, 1024),
    (65536, 4096),
)


def _config_key(chunk_size: int, read_buffer: int) -> str:
    return f"chunk{chunk_size}_buf{read_buffer}"


def _load() -> dict:
    if not VECTORS.exists():
        return {"version": 1, "cases": {}}
    with open(VECTORS) as handle:
        return json.load(handle)


def _record(result) -> dict:
    return {
        "content_digest": result.content_digest,
        "merkle_root": result.merkle_root,
        "chunk_count": len(result.chunks),
        "total_size": result.total_size,
    }


def _all_possible_case_ids() -> set[str]:
    """
    Every case id any tier, config and algorithm could pin.

    Only used to spot orphans: vectors left behind for a case that has since been
    renamed or deleted, which nothing compares and nothing reports. The span is
    deliberately wider than the current run — all algorithms, so a base install
    without the `checksum` extra does not call every blake3 vector stale, and all
    tiers, so a fast run does not call the 256MB vectors stale.
    """
    ids = set()
    for case in FILE_CASES:
        for chunk_size, read_buffer in CONFIGS:
            if case.tier == Tier.full and chunk_size != CHUNK_SIZE:
                continue
            for algorithm in Algorithm:
                ids.add(
                    f"{case.name}.{algorithm.value}."
                    f"{_config_key(chunk_size, read_buffer)}"
                )
    for tree in TREE_CASES:
        for algorithm in Algorithm:
            ids.add(f"tree_{tree.name}.{algorithm.value}.production")
    return ids


def _constants(tier: Tier) -> Iterator[Check]:
    """
    The eval's copy of the production constants must still be the real ones.

    corpus.py restates CHUNK_SIZE and READ_BUFFER so a case can be described
    relative to them without importing the module under test everywhere. If the
    library's values move, the copies keep patching the old ones in: the config
    these vectors label `production` quietly stops being production, and every
    check here keeps passing while measuring a partitioning no caller will ever
    get. Only `scale` would notice, and only at a tier CI does not run.
    """
    yield compare(
        f"{NAME}.production_chunk_size",
        NAME,
        tier,
        CHUNK_SIZE,
        PRODUCTION_CHUNK_SIZE,
        note="the eval's CHUNK_SIZE has drifted from the library's",
    )
    yield compare(
        f"{NAME}.production_read_buffer",
        NAME,
        tier,
        READ_BUFFER,
        PRODUCTION_READ_BUFFER,
        note="the eval's READ_BUFFER has drifted from the library's",
    )


def _fields(case_id: str, tier: Tier, actual: dict, expected: dict) -> Iterator[Check]:
    for field, expected_value in expected.items():
        yield compare(
            f"{NAME}.{case_id}.{field}",
            NAME,
            tier,
            actual.get(field),
            expected_value,
            note="pinned digest changed — stored catalog checksums would not match",
        )


def run(ctx: Context) -> Iterator[Check]:
    from evals.checksum.harness import available_algorithms

    declined = gate(NAME, ctx, Tier.fast)
    if declined:
        yield declined
        return

    algorithms = available_algorithms()
    file_cases, tree_cases = cases_for(ctx.tier)
    vectors = _load()
    recorded: dict[str, dict] = {}
    # Case ids this run expected to find a vector for and did not. Reported in
    # aggregate at the end: a per-case skip says which case is unpinned, but only
    # a verdict makes an unpinned case turn CI red.
    unpinned: list[str] = []
    workdir = ctx.scratch("golden")

    # Yielded even under --update-golden: re-pinning while the constants have
    # drifted would bake the drift into the committed vectors.
    yield from _constants(ctx.tier)

    for case in file_cases:
        directory = workdir / case.name
        directory.mkdir(parents=True, exist_ok=True)
        path = case.materialise(directory)
        try:
            for chunk_size, read_buffer in CONFIGS:
                # A small-chunk configuration on a 256MB body would build a
                # 65,000-entry manifest for no extra signal: the production
                # configuration is the one that matters at that size.
                if case.tier == Tier.full and chunk_size != CHUNK_SIZE:
                    continue
                for algorithm in algorithms:
                    case_id = (
                        f"{case.name}.{algorithm.value}."
                        f"{_config_key(chunk_size, read_buffer)}"
                    )
                    with chunking(chunk_size, read_buffer):
                        result = compute_checksum_localfs(str(path), algorithm)
                    actual = _record(result)

                    if ctx.update_golden:
                        recorded[case_id] = actual
                        continue
                    expected = vectors.get("cases", {}).get(case_id)
                    if expected is None:
                        unpinned.append(case_id)
                        yield skip(
                            f"{NAME}.{case_id}",
                            NAME,
                            case.tier,
                            "no pinned vector; run with --update-golden at this tier",
                        )
                        continue
                    yield from _fields(case_id, case.tier, actual, expected)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    for tree in tree_cases:
        directory = workdir / f"tree_{tree.name}"
        directory.mkdir(parents=True, exist_ok=True)
        root = tree.materialise(directory)
        try:
            for algorithm in algorithms:
                case_id = f"tree_{tree.name}.{algorithm.value}.production"
                with chunking(CHUNK_SIZE, READ_BUFFER):
                    result = compute_checksum_localfs(str(root), algorithm)
                # chunk_count is meaningless for a directory node (it has
                # children, not chunks), so only the digest and total are pinned.
                actual = {
                    "content_digest": result.content_digest,
                    "total_size": result.total_size,
                }

                if ctx.update_golden:
                    recorded[case_id] = actual
                    continue
                expected = vectors.get("cases", {}).get(case_id)
                if expected is None:
                    unpinned.append(case_id)
                    yield skip(
                        f"{NAME}.{case_id}",
                        NAME,
                        tree.tier,
                        "no pinned vector; run with --update-golden at this tier",
                    )
                    continue
                yield from _fields(case_id, tree.tier, actual, expected)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    orphans = sorted(set(vectors.get("cases", {})) - _all_possible_case_ids())

    if not ctx.update_golden:
        # The whole point of this dimension is that a digest change shows up as a
        # failure. An unpinned case is not a digest change, but it is the absence
        # of the anchor, and reported only as a skip it exits 0: renaming a corpus
        # case silently drops its vectors and the run still says PASS.
        yield assert_that(
            f"{NAME}.every_case_is_pinned",
            NAME,
            ctx.tier,
            not unpinned,
            f"{len(unpinned)} case(s) have no committed vector, so nothing anchors "
            f"their digests: {', '.join(unpinned[:5])}"
            f"{' …' if len(unpinned) > 5 else ''} — re-pin with `make eval-golden` "
            "and review the diff",
            unpinned=len(unpinned),
        )
        # Merging on update means a renamed or deleted case leaves its vectors
        # behind forever, compared against nothing. Pruning here would be wrong
        # (a fast re-pin cannot know the full-tier cases), so report instead.
        yield assert_that(
            f"{NAME}.no_orphan_vectors",
            NAME,
            ctx.tier,
            not orphans,
            f"{len(orphans)} vector(s) belong to no current case and anchor "
            f"nothing: {', '.join(orphans[:5])}"
            f"{' …' if len(orphans) > 5 else ''} — delete them from "
            f"{VECTORS.name}",
            orphans=len(orphans),
        )

    if ctx.update_golden:
        # Merge rather than replace: a fast-tier update must not delete the
        # full-tier vectors that only a full run can regenerate.
        merged = dict(vectors.get("cases", {}))
        merged.update(recorded)
        if orphans:
            # Surfaced at the moment someone is already reviewing the diff, since
            # the merge cannot remove them and the compare path will start
            # failing on them from the next run onwards.
            yield skip(
                f"{NAME}.orphan_vectors_kept",
                NAME,
                ctx.tier,
                f"{len(orphans)} vector(s) belong to no current case and were "
                f"kept by the merge: {', '.join(orphans[:5])}"
                f"{' …' if len(orphans) > 5 else ''} — delete them by hand",
            )
        VECTORS.parent.mkdir(parents=True, exist_ok=True)
        with open(VECTORS, "w") as handle:
            json.dump(
                {"version": 1, "cases": dict(sorted(merged.items()))},
                handle,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
        yield Check(
            id=f"{NAME}.vectors_written",
            dimension=NAME,
            tier=ctx.tier,
            status=Status.skipped,
            message=f"wrote {len(recorded)} vectors to {VECTORS} (review the diff)",
            metrics={"vectors": len(recorded), "total_vectors": len(merged)},
        )
