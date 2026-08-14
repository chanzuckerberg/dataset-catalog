"""
Is the reported size the real size?

`total_size` has a failure mode digests do not. It is never counted while
hashing — it is read from storage metadata (`os.fstat`, `ContentLength`, listing
`Size`) so that the stored-checksum fast path can report a size without reading
the object. That makes it a *claim about the platform's bookkeeping* rather than
a property of bytes the code has seen, and the places it can quietly disagree
with reality are exactly the ones no digest test would notice:

  sparse files      apparent size and occupied size differ by orders of
                    magnitude; genomics and imaging assets are frequently sparse
  symlinked files   os.scandir's is_file() follows links, so the target's size
                    is counted under the link's name
  hardlinks         one body, two names — a directory total counts it twice, and
                    that is the correct answer for "bytes this folder presents"
  unknown sizes     a partial sum must become None, never a plausible-looking
                    understatement

Ground truth is os.stat/os.walk (oracles.py), never the library's own walk.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator

from catalog_client.models.asset import AssetType, StoragePlatform
from catalog_client.utils.checksum.generate import for_location
from catalog_client.utils.checksum.hashing import compute_checksum_localfs
from evals.checksum import corpus, oracles
from evals.checksum.corpus import cases_for
from evals.checksum.harness import (
    Check,
    Context,
    Tier,
    assert_that,
    chunking,
    compare,
    skip,
)

NAME = "sizes"

_SPARSE_APPARENT = 64 * 1024 * 1024


def run(ctx: Context) -> Iterator[Check]:
    from evals.checksum.harness import available_algorithms

    algorithm = available_algorithms()[0]
    file_cases, tree_cases = cases_for(ctx.tier)
    workdir = ctx.scratch("sizes")

    for case in file_cases:
        directory = workdir / case.name
        directory.mkdir(parents=True, exist_ok=True)
        path = case.materialise(directory)
        try:
            result = compute_checksum_localfs(str(path), algorithm)
            yield compare(
                f"{NAME}.file.{case.name}",
                NAME,
                case.tier,
                result.total_size,
                oracles.apparent_size(path),
                note="reported size must equal os.stat",
                size_bytes=case.size,
            )
            if case.size == 0:
                # 0 and None are both falsy and mean completely different
                # things: "an empty file" versus "the platform told us nothing".
                yield assert_that(
                    f"{NAME}.file.{case.name}.zero_is_not_none",
                    NAME,
                    case.tier,
                    result.total_size == 0 and result.total_size is not None,
                    f"an empty file reported {result.total_size!r}, expected 0",
                )
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    for tree in tree_cases:
        directory = workdir / f"tree_{tree.name}"
        directory.mkdir(parents=True, exist_ok=True)
        root = tree.materialise(directory)
        try:
            result = compute_checksum_localfs(str(root), algorithm)
            yield compare(
                f"{NAME}.tree.{tree.name}",
                NAME,
                tree.tier,
                result.total_size,
                oracles.apparent_size(root),
                note="a folder total must equal the os.walk sum of its files",
                files=len(tree.files),
            )
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    yield from _chunking_independence(ctx, workdir, algorithm)
    yield from _sparse(ctx, workdir, algorithm)
    yield from _links(ctx, workdir, algorithm)
    yield from _unreadable(ctx, workdir)


def _chunking_independence(ctx: Context, workdir, algorithm) -> Iterator[Check]:
    """A size read from metadata cannot depend on how the bytes were read."""
    path = workdir / "chunking.bin"
    corpus.write(path, "sizes/chunking", 200_003)
    for chunk_size, read_buffer in ((corpus.CHUNK_SIZE, corpus.READ_BUFFER), (4096, 7)):
        with chunking(chunk_size, read_buffer):
            size = compute_checksum_localfs(str(path), algorithm).total_size
        yield compare(
            f"{NAME}.chunking_independent.chunk{chunk_size}_buf{read_buffer}",
            NAME,
            Tier.fast,
            size,
            200_003,
            note="size comes from fstat, so partitioning must not touch it",
        )
    path.unlink()


def _sparse(ctx: Context, workdir, algorithm) -> Iterator[Check]:
    """
    A sparse file must report its apparent size, and hash its holes as zeros.

    Skipped rather than failed where the filesystem does not do sparseness: the
    library's behaviour is right either way, and a false failure on a filesystem
    that materialises the hole would just train people to ignore the eval.
    """
    path = workdir / "sparse.bin"
    with open(path, "wb") as handle:
        handle.truncate(_SPARSE_APPARENT)
        handle.seek(_SPARSE_APPARENT - 4)
        handle.write(b"tail")
    apparent = _SPARSE_APPARENT
    occupied = oracles.allocated_size(path)

    if occupied >= apparent:
        yield skip(
            f"{NAME}.sparse",
            NAME,
            Tier.fast,
            f"filesystem materialised the hole ({occupied} bytes on disk); "
            "nothing sparse to measure here",
        )
    else:
        result = compute_checksum_localfs(str(path), algorithm)
        yield compare(
            f"{NAME}.sparse.apparent_size_reported",
            NAME,
            Tier.fast,
            result.total_size,
            apparent,
            note="a sparse file must report apparent size, not blocks on disk",
            occupied_bytes=occupied,
        )
        yield compare(
            f"{NAME}.sparse.digest_covers_the_hole",
            NAME,
            Tier.fast,
            result.content_digest,
            oracles.digest(path, algorithm),
            note="the hole must hash as the zeros the platform reads back",
        )
    path.unlink()


def _links(ctx: Context, workdir, algorithm) -> Iterator[Check]:
    """Symlinked and hardlinked children, whose sizes are easy to double- or under-count."""
    root = workdir / "links"
    (root / "outside").mkdir(parents=True, exist_ok=True)
    inner = root / "inner"
    inner.mkdir(parents=True, exist_ok=True)

    corpus.write(inner / "real.bin", "sizes/links/real", 1_000)
    target = root / "outside" / "target.bin"
    corpus.write(target, "sizes/links/target", 2_500)

    try:
        (inner / "link.bin").symlink_to(target)
        has_symlink = True
    except (OSError, NotImplementedError):
        has_symlink = False

    try:
        os.link(inner / "real.bin", inner / "hard.bin")
        has_hardlink = True
    except (OSError, NotImplementedError):
        has_hardlink = False

    result = compute_checksum_localfs(str(inner), algorithm)
    yield compare(
        f"{NAME}.links.total",
        NAME,
        Tier.fast,
        result.total_size,
        oracles.apparent_size(inner),
        note="folder total must match os.walk over the same entries",
        symlink=str(has_symlink),
        hardlink=str(has_hardlink),
    )

    if has_symlink:
        # scandir's is_file() follows the link, so the child is present and
        # carries the *target's* size — 1000 + 2500, not 1000 + a link's inode.
        yield assert_that(
            f"{NAME}.links.symlink_counted_as_target",
            NAME,
            Tier.fast,
            "link.bin" in result.children
            and result.children["link.bin"].total_size == 2_500,
            f"symlinked child reported {result.children.get('link.bin')}",
        )
    else:
        yield skip(f"{NAME}.links.symlink", NAME, Tier.fast, "symlinks unavailable")

    if has_hardlink:
        # Two names for one body is genuinely 3500 bytes of folder content, even
        # though `du` would say 2000: the folder presents both names.
        yield compare(
            f"{NAME}.links.hardlink_counted_twice",
            NAME,
            Tier.fast,
            result.children["hard.bin"].total_size,
            result.children["real.bin"].total_size,
            note="both names of one inode count, matching the apparent-size model",
        )
    else:
        yield skip(f"{NAME}.links.hardlink", NAME, Tier.fast, "hardlinks unavailable")

    shutil.rmtree(root, ignore_errors=True)


def _unreadable(ctx: Context, workdir) -> Iterator[Check]:
    """
    A folder with an unreadable child must produce no result, not a partial one.

    An understated total that looks authoritative is the dangerous outcome here:
    `for_location` returning a smaller size with no checksum is fine, returning
    a size that silently omits a file is not.
    """
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        yield skip(
            f"{NAME}.unreadable",
            NAME,
            Tier.fast,
            "running as root, permissions are not enforced",
        )
        return

    root = workdir / "unreadable"
    root.mkdir(parents=True, exist_ok=True)
    corpus.write(root / "readable.bin", "sizes/unreadable/ok", 100)
    blocked = root / "blocked.bin"
    corpus.write(blocked, "sizes/unreadable/no", 100)
    blocked.chmod(0o000)

    try:
        import warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            # Any non-S3 supported platform routes to the local filesystem;
            # sf_hpc is one such POSIX mount.
            outcome = for_location(str(root), AssetType.folder, StoragePlatform.sf_hpc)
        yield assert_that(
            f"{NAME}.unreadable.no_partial_result",
            NAME,
            Tier.fast,
            not outcome and outcome.total_size is None,
            f"expected an empty result, got {outcome}",
            warnings_emitted=len(caught),
        )
        yield assert_that(
            f"{NAME}.unreadable.warns",
            NAME,
            Tier.fast,
            len(caught) > 0,
            "a skipped folder must emit a ChecksumWarning",
        )
    finally:
        blocked.chmod(0o600)
        shutil.rmtree(root, ignore_errors=True)
