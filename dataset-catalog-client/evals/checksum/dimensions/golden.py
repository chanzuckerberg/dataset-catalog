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

from catalog_client.utils.checksum.hashing import compute_checksum_localfs
from evals.checksum.corpus import CHUNK_SIZE, READ_BUFFER, cases_for
from evals.checksum.harness import Check, Context, Status, Tier, chunking, compare, skip

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

    algorithms = available_algorithms()
    file_cases, tree_cases = cases_for(ctx.tier)
    vectors = _load()
    recorded: dict[str, dict] = {} if ctx.update_golden else vectors.get("cases", {})
    workdir = ctx.scratch("golden")

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

    if ctx.update_golden:
        # Merge rather than replace: a fast-tier update must not delete the
        # full-tier vectors that only a full run can regenerate.
        merged = dict(vectors.get("cases", {}))
        merged.update(recorded)
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
