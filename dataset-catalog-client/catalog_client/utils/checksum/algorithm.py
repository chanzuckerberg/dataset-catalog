import hashlib
import struct
import zlib
from enum import StrEnum
from typing import Protocol, runtime_checkable

import crcmod

try:  # Optional: blake3 must be installed separately
    import blake3 as _blake3

    _HAS_BLAKE3 = True
except ImportError:
    _blake3 = None  # type: ignore[assignment]
    _HAS_BLAKE3 = False

try:  # Optional: awscrt is only needed for crc64nvme
    from awscrt.checksums import crc64nvme as _awscrt_crc64nvme

    _HAS_AWSCRT = True
except ImportError:
    _HAS_AWSCRT = False


class Algorithm(StrEnum):
    blake3 = "blake3"
    blake2b = "blake2b"
    crc32 = "crc32"
    crc64 = "crc64"
    crc64nvme = "crc64nvme"


CRC_ALGORITHMS: set[Algorithm] = {Algorithm.crc32, Algorithm.crc64, Algorithm.crc64nvme}
CRYPTO_ALGORITHMS: set[Algorithm] = {Algorithm.blake3, Algorithm.blake2b}


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
    """CRC32 via zlib (stdlib). Streams correctly across update() calls.

    Spec: https://www.rfc-editor.org/rfc/rfc1952#section-8
    Polynomial: 0x04C11DB7 (ISO 3309 / ITU-T V.42 / IEEE 802.3 Ethernet)
    """

    def __init__(self) -> None:
        self._crc: int = 0

    def update(self, data: bytes) -> None:
        self._crc = zlib.crc32(data, self._crc) & 0xFFFFFFFF

    def hexdigest(self) -> str:
        return f"{self._crc:08x}"

    def raw(self) -> bytes:
        return struct.pack(">I", self._crc)


class _CRC64BaseHasher:
    """Shared base for 64-bit CRC hashers (ECMA-182 and NVMe)."""

    def __init__(self) -> None:
        self._crc: int = 0

    def hexdigest(self) -> str:
        return f"{self._crc:016x}"

    def raw(self) -> bytes:
        return struct.pack(">Q", self._crc)


class _CRC64Hasher(_CRC64BaseHasher):
    """
    CRC64/ECMA-182 via crcmod.
    initCrc=0, xorOut=0 allows correct incremental accumulation.

    Spec: https://ecma-international.org/publications-and-standards/standards/ecma-182/
    Polynomial: 0x42F0E1EBA9EA3693
    """

    _FN = crcmod.predefined.mkCrcFun("crc-64")  # built once at class level

    def update(self, data: bytes) -> None:
        self._crc = self._FN(data, self._crc)


class _CRC64NVMEHasher(_CRC64BaseHasher):
    """
    CRC64/NVMe via awscrt — same polynomial used by AWS S3.
    Raises ImportError at instantiation if awscrt is not installed.

    Spec: https://nvmexpress.org/specifications/ (NVM Express Base Spec §Annex I)
    Polynomial: 0xAD93D23594C93659
    AWS S3 support: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
    """

    def __init__(self) -> None:
        if not _HAS_AWSCRT:
            raise ImportError("crc64nvme requires the awscrt package: pip install awscrt")
        super().__init__()

    def update(self, data: bytes) -> None:
        self._crc = _awscrt_crc64nvme(data, self._crc)


def new_hasher(algorithm: Algorithm) -> _Hasher:
    if algorithm == "blake3":
        if not _HAS_BLAKE3:
            raise ImportError("blake3 package required: pip install blake3")
        return _CryptoHasher(_blake3.blake3())  # type: ignore[union-attr]
    elif algorithm == "blake2b":
        """cryptographic hash (RFC 7693); combine chunks via Merkle tree.
        Spec: https://www.rfc-editor.org/rfc/rfc7693"""
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
