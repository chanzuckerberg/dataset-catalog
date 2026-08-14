"""Total size is read from the storage platform, never counted while hashing.

`ChecksumResult.total_size` comes from os.fstat, the S3 ContentLength on the
HeadObject/GetObject responses the module already issues, and the Size field on
the ListObjectsV2 listing it already paginates. Counting bytes in the hash loop
would be both slower and less complete: the stored-checksum path returns
without ever reading the object, so a counter there would leave exactly the
fast path sizeless. test_stored_checksum_reports_size_without_downloading is
the regression guard for that.

S3 cases use moto where real response shapes matter, and MagicMock where the
point is a response that omits a field.
"""

import io
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from catalog_client.models.asset import AssetType, DataAssetRequest, StoragePlatform
from catalog_client.utils.checksum import Algorithm, for_assets, for_location
from catalog_client.utils.checksum.hashing import (
    compute_checksum_localfs,
    compute_checksum_s3,
)

BUCKET = "size-bucket"
BODY = b"the quick brown fox jumps over the lazy dog"  # 43 bytes
HEX64 = "ab" * 32  # valid blake3-length hex digest


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def s3_asset(uri, asset_type, **kwargs):
    return DataAssetRequest(
        location_uri=uri,
        asset_type=asset_type,
        storage_platform=StoragePlatform.s3,
        **kwargs,
    )


# ── Local filesystem ──────────────────────────────────────────────────────────


def test_local_file_size_matches_content_length(tmp_path):
    f = tmp_path / "file.bin"
    f.write_bytes(BODY)
    assert compute_checksum_localfs(str(f), Algorithm.blake2b).total_size == len(BODY)


def test_local_empty_file_size_is_zero_not_none(tmp_path):
    # 0 and None are different claims: "this file has no bytes" versus "we did
    # not learn its size". An empty file must report the former.
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    result = compute_checksum_localfs(str(f), Algorithm.blake2b)
    assert result.total_size == 0
    assert result.total_size is not None


def test_local_directory_size_sums_all_descendants(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"12345")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.bin").write_bytes(b"678")
    (tmp_path / "sub" / "deep").mkdir()
    (tmp_path / "sub" / "deep" / "c.bin").write_bytes(b"9")

    assert compute_checksum_localfs(str(tmp_path), Algorithm.blake2b).total_size == 9


def test_local_empty_directory_size_is_zero(tmp_path):
    assert compute_checksum_localfs(str(tmp_path), Algorithm.blake2b).total_size == 0


@patch("catalog_client.utils.checksum.hashing.READ_BUFFER", 4)
@patch("catalog_client.utils.checksum.hashing.CHUNK_SIZE", 4)
def test_size_is_independent_of_chunking(tmp_path):
    # merkle_root shifts with chunk size (see test_invariance.py); the size must
    # not. Patched on `hashing`, not `models` — that is where they are read.
    f = tmp_path / "data.bin"
    f.write_bytes(BODY)
    result = compute_checksum_localfs(str(f), Algorithm.blake2b)
    assert len(result.chunks) > 1
    assert result.total_size == len(BODY)


# ── S3 ────────────────────────────────────────────────────────────────────────


def test_s3_downloaded_object_size_comes_from_get_object(s3):
    s3.put_object(Bucket=BUCKET, Key="f.bin", Body=BODY)
    result = compute_checksum_s3(
        f"s3://{BUCKET}/f.bin", Algorithm.blake2b, s3, use_stored=False
    )
    assert result.total_size == len(BODY)


def test_stored_checksum_reports_size_without_downloading(s3):
    # The whole point of sourcing size from metadata: a stored checksum short
    # circuits the read, and the size still comes back. A byte counter in
    # _hash_stream could not satisfy this test.
    s3.put_object(Bucket=BUCKET, Key="f.bin", Body=BODY, ChecksumAlgorithm="CRC32")
    s3.get_object = MagicMock(side_effect=AssertionError("must not download"))

    result = compute_checksum_s3(
        f"s3://{BUCKET}/f.bin", Algorithm.crc32, s3, use_stored=True
    )

    assert result.source == "s3_native"
    assert result.total_size == len(BODY)
    s3.get_object.assert_not_called()


def test_s3_metadata_checksum_reports_size(s3):
    s3.put_object(
        Bucket=BUCKET, Key="f.bin", Body=BODY, Metadata={"x-checksum-blake3": HEX64}
    )
    result = compute_checksum_s3(
        f"s3://{BUCKET}/f.bin", Algorithm.blake3, s3, use_stored=True
    )
    assert result.source == "s3_metadata"
    assert result.total_size == len(BODY)


def test_s3_prefix_size_sums_children(s3):
    s3.put_object(Bucket=BUCKET, Key="ds/a.bin", Body=b"12345")
    s3.put_object(Bucket=BUCKET, Key="ds/nested/b.bin", Body=b"678")

    result = compute_checksum_s3(
        f"s3://{BUCKET}/ds/", Algorithm.blake2b, s3, use_stored=False
    )
    assert result.total_size == 8


# ── Missing platform metadata degrades to None, never to a wrong number ───────


def test_head_object_without_content_length_yields_no_size():
    s3 = MagicMock()
    s3.head_object.return_value = {"Metadata": {"x-checksum-blake3": HEX64}}
    result = compute_checksum_s3("s3://b/f.bin", Algorithm.blake3, s3, use_stored=True)
    assert result.file_hash == HEX64
    assert result.total_size is None


def test_get_object_without_content_length_yields_no_size():
    s3 = MagicMock()
    s3.head_object.return_value = {}
    s3.get_object.return_value = {"Body": io.BytesIO(BODY)}
    result = compute_checksum_s3(
        "s3://b/f.bin", Algorithm.blake2b, s3, use_stored=False
    )
    assert result.total_size is None


def test_directory_size_is_none_when_any_child_size_is_unknown():
    # A partial sum would understate the folder while looking authoritative.
    s3 = MagicMock()
    s3.head_object.return_value = {}
    s3.get_object.return_value = {"Body": io.BytesIO(b"x")}
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "ds/known.bin", "Size": 5}, {"Key": "ds/unknown.bin"}]}
    ]
    s3.get_paginator.return_value = paginator

    result = compute_checksum_s3("s3://b/ds/", Algorithm.blake2b, s3, use_stored=False)
    assert result.total_size is None


def test_listing_size_backfills_a_stored_result_that_lacks_content_length():
    # ListObjectsV2 reports the size even when the HeadObject mock omits it, so
    # one incomplete response does not null out the whole folder.
    s3 = MagicMock()
    s3.head_object.return_value = {"Metadata": {"x-checksum-blake3": HEX64}}
    paginator = MagicMock()
    paginator.paginate.return_value = [{"Contents": [{"Key": "ds/f.bin", "Size": 7}]}]
    s3.get_paginator.return_value = paginator

    result = compute_checksum_s3("s3://b/ds/", Algorithm.blake3, s3, use_stored=True)

    assert result.total_size == 7
    s3.get_object.assert_not_called()


# ── for_location / for_assets ─────────────────────────────────────────────────


def test_for_location_carries_the_size(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(BODY)
    checksum = for_location(
        str(f), AssetType.file, storage_platform=StoragePlatform.sf_hpc
    )
    assert checksum.total_size == len(BODY)


def test_for_assets_populates_size_bytes(s3):
    s3.put_object(Bucket=BUCKET, Key="f.bin", Body=BODY)
    asset = s3_asset(f"s3://{BUCKET}/f.bin", AssetType.file)

    result = for_assets([asset], s3_client=s3)[0]

    assert result.size_bytes == len(BODY)
    assert result.checksum is not None


def test_for_assets_populates_size_bytes_for_folders(s3):
    s3.put_object(Bucket=BUCKET, Key="ds/a.bin", Body=b"12345")
    s3.put_object(Bucket=BUCKET, Key="ds/b.bin", Body=b"678")
    asset = s3_asset(f"s3://{BUCKET}/ds/", AssetType.folder)

    assert for_assets([asset], s3_client=s3)[0].size_bytes == 8


def test_for_assets_does_not_overwrite_a_caller_supplied_size(s3):
    s3.put_object(Bucket=BUCKET, Key="f.bin", Body=BODY)
    asset = s3_asset(f"s3://{BUCKET}/f.bin", AssetType.file, size_bytes=999)

    assert for_assets([asset], s3_client=s3)[0].size_bytes == 999


def test_for_assets_does_not_mutate_the_input_asset(s3):
    s3.put_object(Bucket=BUCKET, Key="f.bin", Body=BODY)
    asset = s3_asset(f"s3://{BUCKET}/f.bin", AssetType.file)

    for_assets([asset], s3_client=s3)

    assert asset.size_bytes is None


def test_for_assets_leaves_size_unset_on_unsupported_platforms(s3):
    asset = DataAssetRequest(
        location_uri="https://example.org/f.bin",
        asset_type=AssetType.file,
        storage_platform=StoragePlatform.external,
    )
    with pytest.warns(UserWarning):
        result = for_assets([asset], s3_client=s3)[0]

    assert result.size_bytes is None
    assert result.checksum is None


def test_for_assets_leaves_size_unset_when_download_is_declined():
    # No stored checksum and compute_if_no_s3_checksum=False → the asset is
    # skipped entirely. Size follows the checksum, so it stays None even though
    # HeadObject did report a ContentLength.
    #
    # Mocked rather than moto: real S3 (and moto) attach a CRC32 to every
    # upload, so "an object with no stored checksum" cannot be staged there.
    s3 = MagicMock()
    s3.head_object.return_value = {"ContentLength": len(BODY)}
    asset = s3_asset("s3://b/f.bin", AssetType.file)

    result = for_assets([asset], compute_if_no_s3_checksum=False, s3_client=s3)[0]

    assert result.checksum is None
    assert result.size_bytes is None
    s3.get_object.assert_not_called()


def test_for_assets_uses_the_stored_checksum_and_size_without_downloading(s3):
    # The common real-world case: S3 attaches a CRC32 on upload, so neither a
    # download nor a second metadata call is needed to fill both fields.
    s3.put_object(Bucket=BUCKET, Key="f.bin", Body=BODY)
    asset = s3_asset(f"s3://{BUCKET}/f.bin", AssetType.file)
    s3.get_object = MagicMock(side_effect=AssertionError("must not download"))

    result = for_assets([asset], compute_if_no_s3_checksum=False, s3_client=s3)[0]

    assert result.checksum is not None
    assert result.size_bytes == len(BODY)


def test_for_assets_skips_assets_that_already_have_a_checksum(s3):
    # The existing early-out short circuits before any size lookup.
    s3.put_object(Bucket=BUCKET, Key="f.bin", Body=BODY)
    asset = s3_asset(f"s3://{BUCKET}/f.bin", AssetType.file, checksum=HEX64)

    result = for_assets([asset], s3_client=s3)[0]

    assert result.checksum == HEX64
    assert result.size_bytes is None


# ── The size agrees across the routes that can produce it ─────────────────────


def test_size_same_standalone_and_as_folder_child(s3):
    s3.put_object(Bucket=BUCKET, Key="ds/inner.bin", Body=BODY)

    standalone = compute_checksum_s3(
        f"s3://{BUCKET}/ds/inner.bin", Algorithm.blake2b, s3, use_stored=False
    )
    as_child = compute_checksum_s3(
        f"s3://{BUCKET}/ds/", Algorithm.blake2b, s3, use_stored=False
    ).children["inner.bin"]

    assert standalone.total_size == as_child.total_size == len(BODY)


def test_size_same_whether_stored_or_computed(s3):
    s3.put_object(Bucket=BUCKET, Key="f.bin", Body=BODY, ChecksumAlgorithm="CRC32")
    uri = f"s3://{BUCKET}/f.bin"

    stored = compute_checksum_s3(uri, Algorithm.crc32, s3, use_stored=True)
    computed = compute_checksum_s3(uri, Algorithm.crc32, s3, use_stored=False)

    assert stored.source == "s3_native"
    assert computed.source == "computed"
    assert stored.total_size == computed.total_size == len(BODY)


def test_local_and_s3_agree_on_the_same_content(tmp_path, s3):
    (tmp_path / "f.bin").write_bytes(BODY)
    s3.put_object(Bucket=BUCKET, Key="f.bin", Body=BODY)

    local = compute_checksum_localfs(str(tmp_path / "f.bin"), Algorithm.blake2b)
    remote = compute_checksum_s3(
        f"s3://{BUCKET}/f.bin", Algorithm.blake2b, s3, use_stored=False
    )

    assert local.total_size == remote.total_size
