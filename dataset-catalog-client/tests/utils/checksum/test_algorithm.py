"""Tests for the hasher implementations themselves.

These are the only tests that pin the actual digest values. Everything else in
the checksum suite compares one code path against another, which would stay
green if a polynomial or an incremental-update chain were wrong in the same way
everywhere. Known vectors are the backstop for that.
"""

import hashlib
import zlib

import pytest

from catalog_client.utils.checksum.algorithm import (
    _HAS_AWSCRT,
    _HAS_BLAKE3,
    _HAS_CRCMOD,
    DIGEST_HEX_LENGTH,
    Algorithm,
    default_algorithm,
    hash_bytes_independent,
    is_valid_digest,
    new_hasher,
    raw_from_hex,
)

CHECK = b"123456789"  # the standard CRC check string
LOREM = b"the quick brown fox jumps over the lazy dog" * 97  # spans many updates


# ── Known vectors ─────────────────────────────────────────────────────────────


def test_crc32_matches_the_standard_check_value():
    # CRC-32/ISO-HDLC of "123456789" is 0xCBF43926
    assert hash_bytes_independent(CHECK, Algorithm.crc32) == "cbf43926"


@pytest.mark.skipif(not _HAS_CRCMOD, reason="crc64 requires crcmod")
def test_crc64_ecma182_matches_the_standard_check_value():
    # CRC-64/ECMA-182 of "123456789" is 0x6C40DF5F0B497347
    assert hash_bytes_independent(CHECK, Algorithm.crc64) == "6c40df5f0b497347"


@pytest.mark.skipif(not _HAS_AWSCRT, reason="crc64nvme requires awscrt")
def test_crc64nvme_matches_the_standard_check_value():
    # CRC-64/NVME of "123456789" is 0xAE8B14860A799888
    assert hash_bytes_independent(CHECK, Algorithm.crc64nvme) == "ae8b14860a799888"


def test_blake2b_matches_hashlib():
    assert (
        hash_bytes_independent(CHECK, Algorithm.blake2b)
        == hashlib.blake2b(CHECK).hexdigest()
    )


def test_crc32_matches_zlib():
    assert hash_bytes_independent(CHECK, Algorithm.crc32) == format(
        zlib.crc32(CHECK) & 0xFFFFFFFF, "08x"
    )


# ── Incremental accumulation ──────────────────────────────────────────────────


@pytest.mark.parametrize("algorithm", list(Algorithm))
def test_chained_updates_equal_a_single_update(algorithm):
    """Streaming is only safe if update() chains correctly.

    A CRC configured with the wrong initCrc/xorOut still produces a plausible
    digest in one shot but diverges the moment it is fed in pieces — which is
    exactly how every real file is hashed.
    """
    try:
        chunked = new_hasher(algorithm)
    except ImportError:
        pytest.skip(f"{algorithm} dependency not installed")

    for start in range(0, len(LOREM), 512):
        chunked.update(LOREM[start : start + 512])

    assert chunked.hexdigest() == hash_bytes_independent(LOREM, algorithm)


@pytest.mark.parametrize("algorithm", list(Algorithm))
def test_empty_input_is_hashable(algorithm):
    try:
        assert hash_bytes_independent(b"", algorithm)
    except ImportError:
        pytest.skip(f"{algorithm} dependency not installed")


# ── Digest widths and raw packing ─────────────────────────────────────────────


@pytest.mark.parametrize("algorithm", list(Algorithm))
def test_digest_width_matches_the_declared_length(algorithm):
    try:
        digest = hash_bytes_independent(CHECK, algorithm)
    except ImportError:
        pytest.skip(f"{algorithm} dependency not installed")
    assert len(digest) == DIGEST_HEX_LENGTH[algorithm]


@pytest.mark.parametrize(
    "algorithm, hex_digest, expected",
    [
        (Algorithm.crc32, "cbf43926", b"\xcb\xf4\x39\x26"),
        (Algorithm.crc32, "00000001", b"\x00\x00\x00\x01"),
        (Algorithm.crc64, "6c40df5f0b497347", b"\x6c\x40\xdf\x5f\x0b\x49\x73\x47"),
        (Algorithm.crc64nvme, "0000000000000001", b"\x00" * 7 + b"\x01"),
        (Algorithm.blake2b, "aabb", b"\xaa\xbb"),
    ],
)
def test_raw_from_hex_packs_big_endian_at_the_right_width(
    algorithm, hex_digest, expected
):
    # CRCs are packed as fixed-width big-endian integers, not hex-decoded, so
    # leading zeros survive into the bytes a parent digest is built from.
    assert raw_from_hex(hex_digest, algorithm) == expected


# ── Digest validation ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "algorithm, value, valid",
    [
        (Algorithm.crc32, "cbf43926", True),
        (Algorithm.crc32, "CBF43926", True),  # case-insensitive
        (Algorithm.crc32, "cbf4392", False),  # too short
        (Algorithm.crc32, "cbf439266", False),  # too long
        (Algorithm.crc32, "zzzzzzzz", False),  # not hex
        (Algorithm.blake3, "ab" * 32, True),
        (Algorithm.blake3, "ab" * 31, False),
        (Algorithm.blake2b, "ab" * 64, True),
        (Algorithm.crc64, "0" * 16, True),
        (Algorithm.crc64, "", False),
    ],
)
def test_is_valid_digest(algorithm, value, valid):
    assert is_valid_digest(value, algorithm) is valid


# ── Optional dependencies ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "algorithm, installed, package",
    [
        (Algorithm.blake3, _HAS_BLAKE3, "blake3"),
        (Algorithm.crc64, _HAS_CRCMOD, "crcmod"),
        (Algorithm.crc64nvme, _HAS_AWSCRT, "awscrt"),
    ],
)
def test_optional_algorithms_name_their_package_when_missing(
    algorithm, installed, package
):
    """A missing extra must say which package to install, not fail obscurely."""
    if installed:
        assert new_hasher(algorithm) is not None
        return
    with pytest.raises(ImportError, match=package):
        new_hasher(algorithm)


def test_stdlib_algorithms_never_require_an_extra():
    for algorithm in (Algorithm.blake2b, Algorithm.crc32):
        assert new_hasher(algorithm) is not None


def test_default_algorithm_is_always_constructible():
    """The default must work on a base install, not just with the extra."""
    chosen = default_algorithm()
    assert new_hasher(chosen) is not None
    assert chosen == (Algorithm.blake3 if _HAS_BLAKE3 else Algorithm.blake2b)


def test_unknown_algorithm_is_rejected():
    with pytest.raises(ValueError, match="Unknown algorithm"):
        new_hasher("md5")  # type: ignore[arg-type]
