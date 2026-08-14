"""
Ground truth, computed without touching the code under test.

Every function here reaches the underlying primitive directly — hashlib, zlib,
crcmod, awscrt, blake3, os.stat — in a single whole-object pass. No chunk
manifest, no Merkle combination, no streaming abstraction. That is the whole
point: `catalog_client.utils.checksum` cannot be its own oracle, and the unit
suite's fixed check values only cover one input each.

What this file deliberately does NOT provide is an independent implementation of
the Merkle/composite scheme. Those values are held to account two other ways:
pinned golden vectors (dimensions/golden.py) and real S3 multipart composites
(dimensions/aws_native.py).
"""

from __future__ import annotations

import hashlib
import os
import zlib
from pathlib import Path

from catalog_client.utils.checksum.algorithm import Algorithm

_ORACLE_READ = 1024 * 1024


def _blake3_digest(path: Path) -> str:
    import blake3

    hasher = blake3.blake3()
    with open(path, "rb") as handle:
        while block := handle.read(_ORACLE_READ):
            hasher.update(block)
    return hasher.hexdigest()


def _blake2b_digest(path: Path) -> str:
    hasher = hashlib.blake2b()
    with open(path, "rb") as handle:
        while block := handle.read(_ORACLE_READ):
            hasher.update(block)
    return hasher.hexdigest()


def _crc32_digest(path: Path) -> str:
    crc = 0
    with open(path, "rb") as handle:
        while block := handle.read(_ORACLE_READ):
            crc = zlib.crc32(block, crc)
    return f"{crc & 0xFFFFFFFF:08x}"


def _crc64_digest(path: Path) -> str:
    import crcmod

    # Independently specified here rather than imported from the code under
    # test: if the polynomial in algorithm.py were ever changed, importing it
    # would make this oracle agree with the mistake.
    function = crcmod.mkCrcFun(0x142F0E1EBA9EA3693, initCrc=0, rev=False, xorOut=0)
    crc = 0
    with open(path, "rb") as handle:
        while block := handle.read(_ORACLE_READ):
            crc = function(block, crc)
    return f"{crc:016x}"


def _crc64nvme_digest(path: Path) -> str:
    from awscrt.checksums import crc64nvme

    crc = 0
    with open(path, "rb") as handle:
        while block := handle.read(_ORACLE_READ):
            crc = crc64nvme(block, crc)
    return f"{crc:016x}"


_DIGESTS = {
    Algorithm.blake3: _blake3_digest,
    Algorithm.blake2b: _blake2b_digest,
    Algorithm.crc32: _crc32_digest,
    Algorithm.crc64: _crc64_digest,
    Algorithm.crc64nvme: _crc64nvme_digest,
}


def digest(path: str | Path, algorithm: Algorithm) -> str:
    """The whole-file digest of `path`, computed straight from the primitive."""
    return _DIGESTS[algorithm](Path(path))


def digest_of_bytes(body: bytes, algorithm: Algorithm) -> str:
    """Same, for a body already in memory (used by the AWS tier)."""
    import tempfile

    with tempfile.NamedTemporaryFile() as handle:
        handle.write(body)
        handle.flush()
        return digest(handle.name, algorithm)


def apparent_size(path: str | Path) -> int:
    """
    Total bytes of a file, or of every file under a directory.

    Apparent size (st_size), matching what the library reports, and summed with
    os.walk rather than by asking the library to walk for us. followlinks is off
    and symlinks are counted via lstat==skip: os.walk lists symlinked files
    under `filenames`, and st_size on the link target is what the library's
    os.scandir/is_file path also sees.
    """
    target = Path(path)
    if target.is_file():
        return target.stat().st_size

    total = 0
    for root, _, filenames in os.walk(target, followlinks=False):
        for name in filenames:
            total += os.stat(Path(root) / name).st_size
    return total


def allocated_size(path: str | Path) -> int:
    """
    Bytes actually occupied on disk (st_blocks * 512).

    Only used to prove a sparse file really is sparse, so that the size checks
    are demonstrably testing apparent-vs-allocated and not a file the OS quietly
    materialised in full.
    """
    return os.stat(path).st_blocks * 512
