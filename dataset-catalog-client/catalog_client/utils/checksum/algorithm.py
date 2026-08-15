import hashlib
import struct
import zlib
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

try:  # Optional: crcmod is only needed for crc64
    import crcmod

    _HAS_CRCMOD = True
except ImportError:
    _HAS_CRCMOD = False

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


def default_algorithm() -> Algorithm:
    """
    The algorithm used when the caller does not name one and no stored S3
    checksum is available.

    blake3 is preferred, but it ships in the optional `checksum` extra. Rather
    than failing every default call on a base install, fall back to blake2b,
    which is stdlib and therefore always importable. The chosen algorithm is
    always recorded alongside the digest (DataAssetRequest.checksum_alg), so
    values stay self-describing across installs.
    """
    return Algorithm.blake3 if _HAS_BLAKE3 else Algorithm.blake2b


def available_algorithms() -> set[Algorithm]:
    """
    The algorithms this install can actually compute.

    blake2b and crc32 are stdlib and always present; the other three come from
    the optional `checksum` extra. Callers that pick an algorithm from data
    rather than from an argument — folder auto-detection reads whatever S3
    happens to have stored — must intersect with this, or they will choose an
    algorithm whose hasher raises ImportError halfway through a walk.
    """
    unavailable = set()
    if not _HAS_BLAKE3:
        unavailable.add(Algorithm.blake3)
    if not _HAS_CRCMOD:
        unavailable.add(Algorithm.crc64)
    if not _HAS_AWSCRT:
        unavailable.add(Algorithm.crc64nvme)
    return set(Algorithm) - unavailable


class _Hasher(Protocol):
    def update(self, data: bytes) -> None: ...

    def hexdigest(self) -> str: ...


class _CryptoHasher:
    """Wraps blake3 / blake2b."""

    def __init__(self, h):
        self._h = h

    def update(self, data: bytes) -> None:
        self._h.update(data)

    def hexdigest(self) -> str:
        return self._h.hexdigest()


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


class _CRC64BaseHasher:
    """Shared base for 64-bit CRC hashers (ECMA-182 and NVMe)."""

    def __init__(self) -> None:
        self._crc: int = 0

    def hexdigest(self) -> str:
        return f"{self._crc:016x}"


_CRC64_FN: Callable[[bytes, int], int] | None = None

# CRC-64/ECMA-182, given to crcmod with the implicit top bit set.
# NOT crcmod.predefined "crc-64", which is a different variant (reflected,
# polynomial 0x1B) whose check value is 0x46A5A9388A5BEFFE rather than
# ECMA-182's 0x6C40DF5F0B497347 — see tests/utils/checksum/test_algorithm.py.
_CRC64_ECMA182_POLY = 0x142F0E1EBA9EA3693


def _crc64_fn() -> Callable[[bytes, int], int]:
    """Build the CRC64/ECMA-182 function once, on first use.

    Built lazily rather than at import time so that importing catalog_client
    does not require the optional crcmod package.

    initCrc=0 and xorOut=0 are what make chained calls — fn(data, previous) —
    accumulate correctly, which is how every multi-buffer read is hashed.
    """
    global _CRC64_FN
    if _CRC64_FN is None:
        if not _HAS_CRCMOD:
            raise ImportError("crc64 requires the crcmod package: pip install crcmod")
        _CRC64_FN = crcmod.mkCrcFun(_CRC64_ECMA182_POLY, initCrc=0, rev=False, xorOut=0)
    return _CRC64_FN


class _CRC64Hasher(_CRC64BaseHasher):
    """
    CRC64/ECMA-182 via crcmod.
    initCrc=0, xorOut=0 allows correct incremental accumulation.
    Raises ImportError at instantiation if crcmod is not installed.

    Spec: https://ecma-international.org/publications-and-standards/standards/ecma-182/
    Polynomial: 0x42F0E1EBA9EA3693 (non-reflected)
    Check value: CRC64("123456789") == 0x6C40DF5F0B497347
    """

    def __init__(self) -> None:
        self._fn = _crc64_fn()
        super().__init__()

    def update(self, data: bytes) -> None:
        self._crc = self._fn(data, self._crc)


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
            raise ImportError(
                "crc64nvme requires the awscrt package: pip install awscrt"
            )
        super().__init__()

    def update(self, data: bytes) -> None:
        self._crc = _awscrt_crc64nvme(data, self._crc)


def new_hasher(algorithm: Algorithm) -> _Hasher:
    if algorithm == Algorithm.blake3:
        if not _HAS_BLAKE3:
            raise ImportError("blake3 package required: pip install blake3")
        return _CryptoHasher(_blake3.blake3())  # type: ignore[union-attr]
    elif algorithm == Algorithm.blake2b:
        # Cryptographic hash (RFC 7693); combine chunks via Merkle tree.
        # Spec: https://www.rfc-editor.org/rfc/rfc7693
        return _CryptoHasher(hashlib.blake2b())
    elif algorithm == Algorithm.crc32:
        return _CRC32Hasher()
    elif algorithm == Algorithm.crc64:
        return _CRC64Hasher()
    elif algorithm == Algorithm.crc64nvme:
        return _CRC64NVMEHasher()
    raise ValueError(f"Unknown algorithm: {algorithm!r}")


def hash_bytes_independent(data: bytes, algorithm: Algorithm) -> str:
    """Hash a single buffer with a fresh hasher — for per-chunk use."""
    h = new_hasher(algorithm)
    h.update(data)
    return h.hexdigest()


# Hex-digest width per algorithm. A digest of the wrong width cannot be packed
# into the raw bytes a parent directory combines, so widths are checked at the
# point a digest enters the system rather than failing later inside struct.pack.
DIGEST_HEX_LENGTH: dict[Algorithm, int] = {
    Algorithm.blake3: 64,  # 32 bytes
    Algorithm.blake2b: 128,  # 64 bytes
    Algorithm.crc32: 8,  # 4 bytes
    Algorithm.crc64: 16,  # 8 bytes
    Algorithm.crc64nvme: 16,  # 8 bytes
}


def is_valid_digest(hex_digest: str, algorithm: Algorithm) -> bool:
    """
    Whether hex_digest is a usable digest for this algorithm.

    Rejects anything that is not hex of the algorithm's exact width. A value
    that fails this check cannot participate in a folder digest, so admitting
    it would make a file's checksum depend on whether it was hashed standalone
    or as a folder child.
    """
    expected = DIGEST_HEX_LENGTH.get(algorithm)
    if expected is None or len(hex_digest) != expected:
        return False
    try:
        int(hex_digest, 16)
    except ValueError:
        return False
    return True


def raw_from_hex(hex_digest: str, algorithm: Algorithm) -> bytes:
    """
    Convert a hex digest to the raw bytes used when combining child digests.

    For CRCs this is the integer packed as big-endian bytes (4 for crc32,
    8 for crc64/crc64nvme), not a raw hex decode. Lives here beside the hasher
    definitions so digest widths are declared in exactly one place.
    """
    if algorithm == Algorithm.crc32:
        return struct.pack(">I", int(hex_digest, 16))
    elif algorithm in (Algorithm.crc64, Algorithm.crc64nvme):
        return struct.pack(">Q", int(hex_digest, 16))
    return bytes.fromhex(hex_digest)
