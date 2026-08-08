"""Tests for reading checksums off S3 objects.

Covers the shapes HeadObject can return that the happy path does not: multipart
composite checksums, error responses, and the prefix normalisation that keeps
detection and hashing looking at the same set of objects.
"""

import base64
from unittest.mock import MagicMock

import pytest

from catalog_client.utils.checksum.algorithm import Algorithm
from catalog_client.utils.checksum.s3 import (
    _b64_to_hex,
    _fetch_all_s3_stored_checksums,
    _folder_prefix,
    _has_multipart_suffix,
    _is_composite,
    _missing_object_error_code,
)

CRC32_HEX = "cbf43926"
CRC32_B64 = base64.b64encode(bytes.fromhex(CRC32_HEX)).decode()


def _head_client(head):
    s3 = MagicMock()
    s3.head_object.return_value = head
    return s3


def _client_error(code):
    exc = Exception(f"simulated {code}")
    exc.response = {"Error": {"Code": code}}  # type: ignore[attr-defined]
    return exc


# ── Multipart suffix detection ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value, expected",
    [
        (f"{CRC32_B64}-23", True),
        (f"{CRC32_B64}-1", True),
        (CRC32_B64, False),
        ("abc+/def==", False),  # base64 alphabet has no '-'
        ("abc-notanumber", False),  # trailing part must be a part count
    ],
)
def test_has_multipart_suffix(value, expected):
    assert _has_multipart_suffix(value) is expected


@pytest.mark.parametrize(
    "head, value, expected, why",
    [
        ({"ChecksumType": "COMPOSITE"}, CRC32_B64, True, "explicit field wins"),
        (
            {"ChecksumType": "FULL_OBJECT"},
            f"{CRC32_B64}-9",
            False,
            "explicit field wins",
        ),
        ({}, f"{CRC32_B64}-9", True, "fall back to the suffix"),
        ({}, CRC32_B64, False, "no field, no suffix"),
    ],
)
def test_is_composite(head, value, expected, why):
    assert _is_composite(head, value) is expected, why


# ── Composite checksums are not whole-object checksums ────────────────────────


def test_composite_native_checksum_is_not_offered_as_a_stored_checksum():
    """A composite covers part checksums, not the object's bytes.

    Its value depends on the uploader's part size, which we cannot reproduce,
    so treating it as a whole-object hash would make the same content hash
    differently depending on how it happened to be uploaded.
    """
    s3 = _head_client({"ChecksumCRC32": f"{CRC32_B64}-23", "ChecksumType": "COMPOSITE"})

    result = _fetch_all_s3_stored_checksums("b", "k", s3)

    assert Algorithm.crc32 not in result


def test_composite_detected_by_suffix_alone_is_also_excluded():
    s3 = _head_client({"ChecksumCRC32": f"{CRC32_B64}-2"})
    assert Algorithm.crc32 not in _fetch_all_s3_stored_checksums("b", "k", s3)


def test_full_object_native_checksum_is_used():
    s3 = _head_client({"ChecksumCRC32": CRC32_B64, "ChecksumType": "FULL_OBJECT"})

    result = _fetch_all_s3_stored_checksums("b", "k", s3)

    assert result[Algorithm.crc32].file_hash == CRC32_HEX
    assert result[Algorithm.crc32].source == "s3_native"


def test_composite_crc32_does_not_hide_a_good_metadata_checksum():
    s3 = _head_client(
        {
            "ChecksumCRC32": f"{CRC32_B64}-4",
            "Metadata": {"x-checksum-blake2b": "ab" * 64},
        }
    )

    result = _fetch_all_s3_stored_checksums("b", "k", s3)

    assert Algorithm.crc32 not in result
    assert result[Algorithm.blake2b].file_hash == "ab" * 64


# ── Error handling ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("code", ["404", "NoSuchKey", "NotFound"])
def test_missing_object_yields_no_checksums(code):
    s3 = MagicMock()
    s3.head_object.side_effect = _client_error(code)

    assert _fetch_all_s3_stored_checksums("b", "k", s3) == {}


@pytest.mark.parametrize("code", ["AccessDenied", "403", "SlowDown", "ExpiredToken"])
def test_access_and_throttling_errors_propagate(code):
    """These are not "the object has no checksum".

    Reporting them as an empty result would silently trigger a full download,
    or a silent skip when compute_if_no_s3_checksum=False.
    """
    s3 = MagicMock()
    s3.head_object.side_effect = _client_error(code)

    with pytest.raises(Exception, match=code):
        _fetch_all_s3_stored_checksums("b", "k", s3)


def test_non_client_errors_propagate():
    s3 = MagicMock()
    s3.head_object.side_effect = TimeoutError("connection timed out")

    with pytest.raises(TimeoutError):
        _fetch_all_s3_stored_checksums("b", "k", s3)


@pytest.mark.parametrize(
    "exc, expected",
    [
        (_client_error("404"), "404"),
        (TimeoutError("nope"), None),
        (ValueError("no response attr"), None),
    ],
)
def test_missing_object_error_code_reads_botocore_shapes(exc, expected):
    assert _missing_object_error_code(exc) == expected


def test_undecodable_native_value_is_skipped_not_fatal():
    s3 = _head_client({"ChecksumCRC32": "!!!not base64!!!"})
    assert _fetch_all_s3_stored_checksums("b", "k", s3) == {}


# ── Prefix normalisation ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "key, expected",
    [
        ("ds", "ds/"),
        ("ds/", "ds/"),
        ("a/b/c", "a/b/c/"),
        ("", ""),  # bucket root
    ],
)
def test_folder_prefix_normalisation(key, expected):
    assert _folder_prefix(key) == expected


def test_b64_to_hex_round_trip():
    assert _b64_to_hex(CRC32_B64) == CRC32_HEX
