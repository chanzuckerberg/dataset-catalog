import hashlib
import struct
import zlib
from typing import Literal, Protocol, runtime_checkable

import blake3
import crcmod

try:  # Optional: awscrt is only needed for crc64nvme
    from awscrt.checksums import crc64nvme as _awscrt_crc64nvme

    _HAS_AWSCRT = True
except ImportError:
    _HAS_AWSCRT = False


Algorithm = Literal["blake3", "blake2b", "crc32", "crc64", "crc64nvme"]

CRC_ALGORITHMS = {"crc32", "crc64", "crc64nvme"}
CRYPTO_ALGORITHMS = {"blake3", "blake2b"}


@runtime_checkable
class _Hasher(Protocol):
    def update(self, data: bytes) -> None:
        pass

    def hexdigest(self) -> str:
        pass

    def raw(self) -> bytes:
        """Returns the digest as raw bytes for use when combining chunk digests."""
        pass


class _CryptoHasher:
    """Wraps blake3 / blake2b."""

    def __init__(self, h):
        self._h = h

    def update(self, data: bytes) -> None:
        self._h.update(data)

    def hexdigest(self) -> str:
        return self._h.hexdigest()

    def raw(self) -> bytes:
        return bytes.fromhex(self._h.hexdigest())


class _CRC32Hasher:
    """CRC32 via zlib (stdlib). Streams correctly across update() calls."""

    def __init__(self) -> None:
        self._crc: int = 0

    def update(self, data: bytes) -> None:
        self._crc = zlib.crc32(data, self._crc) & 0xFFFFFFFF

    def hexdigest(self) -> str:
        return f"{self._crc:08x}"

    def raw(self) -> bytes:
        return struct.pack(">I", self._crc)


class _CRC64Hasher:
    """
    CRC64/ECMA-182 via crcmod.
    initCrc=0, xorOut=0 allows correct incremental accumulation.
    """

    _FN = crcmod.predefined.mkCrcFun("crc-64")  # built once at class level

    def __init__(self) -> None:
        self._crc: int = 0

    def update(self, data: bytes) -> None:
        self._crc = self._FN(data, self._crc)

    def hexdigest(self) -> str:
        return f"{self._crc:016x}"

    def raw(self) -> bytes:
        return struct.pack(">Q", self._crc)


class _CRC64NVMEHasher:
    """
    CRC64/NVME via awscrt — same polynomial used by AWS S3.
    Raises ImportError at instantiation if awscrt is not installed.
    """

    def __init__(self) -> None:
        if not _HAS_AWSCRT:
            raise ImportError(
                "crc64nvme requires the awscrt package: pip install awscrt"
            )
        self._crc: int = 0

    def update(self, data: bytes) -> None:
        self._crc = _awscrt_crc64nvme(data, self._crc)

    def hexdigest(self) -> str:
        return f"{self._crc:016x}"

    def raw(self) -> bytes:
        return struct.pack(">Q", self._crc)


def new_hasher(algorithm: Algorithm) -> _Hasher:
    if algorithm == "blake3":
        return _CryptoHasher(blake3.blake3())
    elif algorithm == "blake2b":
        return _CryptoHasher(hashlib.blake2b())
    elif algorithm == "crc32":
        return _CRC32Hasher()
    elif algorithm == "crc64":
        return _CRC64Hasher()
    elif algorithm == "crc64nvme":
        return _CRC64NVMEHasher()
    raise ValueError(f"Unknown algorithm: {algorithm!r}")


def hash_bytes_independent(data: bytes, algorithm: Algorithm) -> str:
    """Hash a single buffer with a fresh hasher — for per-chunk use."""
    h = new_hasher(algorithm)
    h.update(data)
    return h.hexdigest()
