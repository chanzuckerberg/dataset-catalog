"""
Deterministic corpus generation.

Nothing here is committed to the repo: every fixture is regenerated from a
label, so a 1GB case costs disk only while it is being hashed. Committed golden
digests are only meaningful if that regeneration is byte-identical forever,
which drives the two choices below:

  SHAKE128 as the byte source, not `random.Random`. SHAKE is a standardised XOF
  (FIPS 202) whose output for a given input is fixed for all time and all
  platforms. `random` guarantees no such thing across Python versions, and a
  corpus that shifts under an interpreter upgrade would invalidate every pinned
  digest at once.

  Content derived from a label, not from a size. Two cases of the same size get
  different bytes, so a case can never accidentally alias another one's digest.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from evals.checksum.harness import Tier

# Production constants, restated so a case can be described relative to them
# without importing the module under test into every call site.
CHUNK_SIZE = 256 * 1024 * 1024
READ_BUFFER = 64 * 1024

_GENERATE_BLOCK = 1024 * 1024


def byte_stream(label: str, size: int) -> Iterator[bytes]:
    """Yield exactly `size` deterministic bytes for `label`, a block at a time."""
    remaining = size
    counter = 0
    while remaining > 0:
        want = min(_GENERATE_BLOCK, remaining)
        seed = f"{label}/{counter}".encode()
        yield hashlib.shake_128(seed).digest(want)
        remaining -= want
        counter += 1


def content(label: str, size: int) -> bytes:
    """The full body for a case. Only for sizes small enough to hold in memory."""
    return b"".join(byte_stream(label, size))


def write(path: Path, label: str, size: int) -> Path:
    """Materialise a case on disk without ever holding it all in memory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        for block in byte_stream(label, size):
            handle.write(block)
    return path


@dataclass(frozen=True)
class FileCase:
    name: str
    size: int
    tier: Tier = Tier.fast
    why: str = ""

    @property
    def label(self) -> str:
        # The digest identity of a case is (name, size); folding both into the
        # label means renaming a case cannot silently keep an old golden digest.
        return f"{self.name}:{self.size}"

    def materialise(self, directory: Path) -> Path:
        return write(directory / f"{self.name}.bin", self.label, self.size)

    def body(self) -> bytes:
        return content(self.label, self.size)


# Sizes chosen around the two constants that partition a read: READ_BUFFER
# (64KB) bounds a single `stream.read`, CHUNK_SIZE (256MB) bounds a manifest
# entry. Every off-by-one in the read loop lives at one of these edges.
FILE_CASES: tuple[FileCase, ...] = (
    FileCase("empty", 0, why="0 bytes must still yield a digest, and size 0 not None"),
    FileCase("single_byte", 1, why="smallest non-empty body"),
    FileCase("sub_buffer", 8_191, why="one short read, no boundary"),
    FileCase("buffer_minus_one", READ_BUFFER - 1),
    FileCase("buffer_exact", READ_BUFFER, why="read loop ends exactly on a boundary"),
    FileCase("buffer_plus_one", READ_BUFFER + 1, why="a 1-byte trailing read"),
    FileCase("many_buffers", 1024 * 1024 + 7, why="16 buffers plus a ragged tail"),
    FileCase("sixteen_mb", 16 * 1024 * 1024, why="largest CI-safe body"),
    FileCase(
        "chunk_minus_one",
        CHUNK_SIZE - 1,
        Tier.full,
        "one byte short of a second chunk at production settings",
    ),
    FileCase(
        "chunk_exact",
        CHUNK_SIZE,
        Tier.full,
        "the exact production chunk boundary, never exercised by the unit suite",
    ),
    FileCase(
        "chunk_plus_one",
        CHUNK_SIZE + 1,
        Tier.full,
        "forces a real second chunk holding a single byte",
    ),
)


@dataclass(frozen=True)
class TreeCase:
    """A directory case, described as relative path -> size."""

    name: str
    files: dict[str, int]
    tier: Tier = Tier.fast
    why: str = ""
    empty_dirs: tuple[str, ...] = field(default=())

    def materialise(self, directory: Path) -> Path:
        root = directory / self.name
        root.mkdir(parents=True, exist_ok=True)
        for relative, size in sorted(self.files.items()):
            write(root / relative, f"{self.name}:{relative}:{size}", size)
        for relative in self.empty_dirs:
            (root / relative).mkdir(parents=True, exist_ok=True)
        return root


TREE_CASES: tuple[TreeCase, ...] = (
    TreeCase("flat", {"a.bin": 10, "b.bin": 4_096, "c.bin": 0}),
    TreeCase(
        "nested",
        {
            "top.bin": 128,
            "one/mid.bin": 70_000,
            "one/two/deep.bin": 3,
            "one/two/three/deepest.bin": 65_537,
        },
        why="every level must roll up into the root digest and the size total",
    ),
    TreeCase(
        "duplicate_bodies",
        {"first/same.bin": 512, "second/same.bin": 512},
        why="identical names and sizes in different parents",
    ),
    TreeCase("only_empty_dirs", {}, empty_dirs=("x", "y/z"), why="no files at all"),
    TreeCase(
        "wide",
        {f"f{index:03d}.bin": index * 13 for index in range(64)},
        why="child ordering must be by name, not by filesystem order",
    ),
)


def cases_for(tier: Tier) -> tuple[tuple[FileCase, ...], tuple[TreeCase, ...]]:
    """The file and tree cases a given requested tier should cover."""
    from evals.checksum.harness import tier_includes

    return (
        tuple(case for case in FILE_CASES if tier_includes(tier, case.tier)),
        tuple(case for case in TREE_CASES if tier_includes(tier, case.tier)),
    )
