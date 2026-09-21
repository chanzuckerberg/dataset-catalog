"""Unit tests for catalog_client.utils.checksum.generate — for_assets and for_location.

All I/O is mocked; no real files, S3 calls, or network access.
"""

import io
import warnings
from unittest.mock import MagicMock, patch

import pytest

from catalog_client.models.asset import (
    AssetType,
    DataAssetRequest,
    DataAssetResponse,
    StoragePlatform,
)
from catalog_client.utils.checksum._parallel import DEFAULT_S3_WORKERS
from catalog_client.utils.checksum.algorithm import (
    Algorithm,
    default_algorithm,
)
from catalog_client.utils.checksum.generate import (
    UNSUPPORTED_PLATFORMS,
    ChecksumWarning,
    for_assets,
    for_location,
)
from catalog_client.utils.checksum.models import ChecksumResult
from tests.utils.checksum.stub_s3 import StubObject, StubS3

# ── Helpers ───────────────────────────────────────────────────────────────────

S3_FILE = "s3://bucket/data/file.h5ad"
S3_FOLDER = "s3://bucket/data/folder"
LOCAL_FILE = "/data/local/file.h5ad"
LOCAL_FOLDER = "/data/local/folder"
HASH = "deadbeefdeadbeef"


def make_asset(
    uri,
    asset_type=AssetType.file,
    platform=StoragePlatform.s3,
    checksum=None,
    checksum_alg=None,
):
    return DataAssetRequest(
        location_uri=uri,
        asset_type=asset_type,
        storage_platform=platform,
        checksum=checksum,
        checksum_alg=checksum_alg,
    )


def make_result(uri, algorithm=Algorithm.blake3, file_hash=HASH, is_directory=False):
    return ChecksumResult(
        path=uri,
        algorithm=algorithm,
        file_hash=file_hash,
        merkle_root=file_hash,
        is_directory=is_directory,
    )


@pytest.fixture()
def mock_s3():
    return MagicMock()


# ── Input-level ───────────────────────────────────────────────────────────────


def test_empty_asset_list_returns_empty(mock_s3):
    assert for_assets([], s3_client=mock_s3) == []


def test_asset_with_existing_checksum_passed_through_unchanged(mock_s3):
    asset = make_asset(S3_FILE, checksum="existing_hash", checksum_alg="blake3")
    with patch("catalog_client.utils.checksum.generate.for_location") as mock_fl:
        result = for_assets([asset], s3_client=mock_s3)
    mock_fl.assert_not_called()
    assert result[0].checksum == "existing_hash"
    assert result[0].checksum_alg == "blake3"


# ── Unsupported platforms ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "platform",
    [StoragePlatform.external, StoragePlatform.other],
    ids=["external", "other"],
)
def test_unsupported_platform_warns_and_leaves_checksum_unset(mock_s3, platform):
    asset = make_asset(LOCAL_FILE, asset_type=AssetType.file, platform=platform)
    with pytest.warns(ChecksumWarning):
        result = for_assets([asset], s3_client=mock_s3)
    assert result[0].checksum is None
    assert result[0].checksum_alg is None


def test_missing_platform_warns_and_leaves_checksum_unset(mock_s3):
    """storage_platform is required on DataAssetRequest but optional on
    DataAssetResponse, so a None platform only reaches for_assets via a response."""
    asset = DataAssetResponse(
        location_uri=LOCAL_FILE,
        asset_type=AssetType.file,
        id="asset-1",
        tombstoned=False,
        created_at="2026-01-01T00:00:00Z",
        last_modified_at="2026-01-01T00:00:00Z",
        dataset_id="dataset-1",
    )
    assert asset.storage_platform is None
    with pytest.warns(ChecksumWarning):
        result = for_assets([asset], s3_client=mock_s3)
    assert result[0].checksum is None
    assert result[0].checksum_alg is None


# ── S3 file ───────────────────────────────────────────────────────────────────


@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={Algorithm.crc64: make_result(S3_FILE, Algorithm.crc64, HASH)},
)
def test_s3_file_stored_checksum_returned_without_download(mock_fetch, mock_s3):
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate._hash_s3_file") as mock_compute:
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=True)
    mock_compute.assert_not_called()
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc64


@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={},
)
@patch(
    "catalog_client.utils.checksum.generate._hash_s3_file",
    return_value=make_result(S3_FILE, Algorithm.blake3, HASH),
)
def test_s3_file_no_stored_checksum_falls_back_to_blake3(
    mock_compute, mock_fetch, mock_s3
):
    asset = make_asset(S3_FILE, AssetType.file)
    result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=True)
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.blake3
    assert result[0].checksum == HASH


@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={Algorithm.crc32: make_result(S3_FILE, Algorithm.crc32, HASH)},
)
def test_s3_file_stored_checksum_returned_when_compute_flag_false(mock_fetch, mock_s3):
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate._hash_s3_file") as mock_compute:
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_not_called()
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc32


@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={},
)
def test_s3_file_no_stored_no_compute_flag_leaves_checksum_unset(mock_fetch, mock_s3):
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate._hash_s3_file") as mock_compute:
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_not_called()
    assert result[0].checksum is None


@patch(
    "catalog_client.utils.checksum.generate._hash_s3_file",
    return_value=make_result(S3_FILE, Algorithm.crc32, HASH),
)
def test_s3_file_explicit_algo_with_compute_flag_downloads_and_computes(
    mock_compute, mock_s3
):
    asset = make_asset(S3_FILE, AssetType.file)
    result = for_assets(
        [asset],
        algorithm=Algorithm.crc32,
        s3_client=mock_s3,
        compute_if_no_s3_checksum=True,
    )
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.crc32
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc32


def test_s3_file_explicit_algo_no_compute_flag_skips_download(mock_s3):
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate._hash_s3_file") as mock_compute:
        result = for_assets(
            [asset],
            algorithm=Algorithm.crc32,
            s3_client=mock_s3,
            compute_if_no_s3_checksum=False,
        )
    mock_compute.assert_not_called()
    assert result[0].checksum is None


# ── S3 file — explicit algorithm, stored checksum present ────────────────────


@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={Algorithm.crc32: make_result(S3_FILE, Algorithm.crc32, HASH)},
)
def test_s3_file_explicit_algo_matching_stored_compute_flag_true_uses_stored(
    mock_fetch, mock_s3
):
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate._hash_s3_file") as mock_compute:
        result = for_assets(
            [asset],
            algorithm=Algorithm.crc32,
            s3_client=mock_s3,
            compute_if_no_s3_checksum=True,
        )
    mock_compute.assert_not_called()
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc32


@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={Algorithm.crc32: make_result(S3_FILE, Algorithm.crc32, HASH)},
)
def test_s3_file_explicit_algo_matching_stored_compute_flag_false_uses_stored(
    mock_fetch, mock_s3
):
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate._hash_s3_file") as mock_compute:
        result = for_assets(
            [asset],
            algorithm=Algorithm.crc32,
            s3_client=mock_s3,
            compute_if_no_s3_checksum=False,
        )
    mock_compute.assert_not_called()
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc32


@patch(
    "catalog_client.utils.checksum.generate._hash_s3_file",
    return_value=make_result(S3_FILE, Algorithm.crc32, HASH),
)
@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={Algorithm.blake3: make_result(S3_FILE, Algorithm.blake3, HASH)},
)
def test_s3_file_explicit_algo_mismatched_stored_compute_flag_true_downloads_and_computes(
    mock_fetch, mock_compute, mock_s3
):
    asset = make_asset(S3_FILE, AssetType.file)
    result = for_assets(
        [asset],
        algorithm=Algorithm.crc32,
        s3_client=mock_s3,
        compute_if_no_s3_checksum=True,
    )
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.crc32
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc32


@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={Algorithm.blake3: make_result(S3_FILE, Algorithm.blake3, HASH)},
)
def test_s3_file_explicit_algo_mismatched_stored_compute_flag_false_leaves_checksum_unset(
    mock_fetch, mock_s3
):
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate._hash_s3_file") as mock_compute:
        result = for_assets(
            [asset],
            algorithm=Algorithm.crc32,
            s3_client=mock_s3,
            compute_if_no_s3_checksum=False,
        )
    mock_compute.assert_not_called()
    assert result[0].checksum is None


# ── S3 folder ─────────────────────────────────────────────────────────────────
#
# Driven through StubS3 rather than mocks of the selection/compute pair: the
# folder route is now one discover-select-resolve-fold pipeline, so there is no
# intermediate call whose arguments would prove anything. What the tests assert
# instead is the observable contract — which requests were issued, what landed
# in the caller's cache, and whether a digest was reported at all.

_CHILD_URI = "s3://bucket/data/folder/file.h5ad"


def _folder_stub(*objects, page_size=1000):
    return StubS3([*objects], page_size=page_size)


def _blake3_child(key, body=b"payload"):
    return StubObject(key=f"data/folder/{key}", body=body).with_metadata(
        Algorithm.blake3
    )


def _folder_asset():
    return make_asset(S3_FOLDER, AssetType.folder)


def test_s3_folder_full_coverage_builds_digest_without_downloading():
    s3 = _folder_stub(_blake3_child("a.h5ad"), _blake3_child("b.h5ad", b"other"))
    cache = {}

    result = for_location(
        S3_FOLDER,
        AssetType.folder,
        StoragePlatform.s3,
        None,
        s3,
        cache,
        compute_if_no_s3_checksum=True,
    )

    assert s3.gets == []
    assert sorted(cache) == [
        "s3://bucket/data/folder/a.h5ad",
        "s3://bucket/data/folder/b.h5ad",
    ]
    assert result.value


def test_s3_folder_with_nothing_stored_falls_back_to_the_default_algorithm():
    s3 = _folder_stub(StubObject(key="data/folder/a.h5ad", body=b"payload"))

    result = for_assets([_folder_asset()], s3_client=s3, compute_if_no_s3_checksum=True)

    assert s3.gets == ["data/folder/a.h5ad"]
    assert result[0].checksum_alg == default_algorithm()


def test_s3_folder_full_coverage_is_assembled_even_with_downloads_disabled():
    # Every child carries a stored blake3, so assembling the folder digest needs
    # no download and compute_if_no_s3_checksum=False must not block it.
    s3 = _folder_stub(_blake3_child("a.h5ad"), _blake3_child("b.h5ad", b"other"))

    result = for_assets(
        [_folder_asset()], s3_client=s3, compute_if_no_s3_checksum=False
    )

    assert s3.gets == []
    assert result[0].checksum


def test_s3_folder_auto_detect_matches_explicit_algo_under_no_compute_flag():
    # Regression guard for the asymmetry itself: algorithm=None and an explicit
    # algorithm must reach the same outcome when that is what selection picks.
    body = b"payload"
    native = StubObject(key="data/folder/a.h5ad", body=body).with_native(
        Algorithm.crc32
    )

    auto = for_assets(
        [_folder_asset()],
        s3_client=_folder_stub(native),
        compute_if_no_s3_checksum=False,
    )
    explicit = for_assets(
        [_folder_asset()],
        algorithm=Algorithm.crc32,
        s3_client=_folder_stub(native),
        compute_if_no_s3_checksum=False,
    )

    assert auto[0].checksum == explicit[0].checksum
    assert auto[0].checksum_alg == explicit[0].checksum_alg == Algorithm.crc32


def test_s3_folder_with_nothing_stored_and_no_compute_flag_leaves_checksum_unset():
    s3 = _folder_stub(StubObject(key="data/folder/a.h5ad", body=b"payload"))

    result = for_assets(
        [_folder_asset()], s3_client=s3, compute_if_no_s3_checksum=False
    )

    assert s3.gets == []
    assert result[0].checksum is None


def test_s3_folder_partial_coverage_no_compute_flag_skips():
    # Partial coverage is not complete coverage. The uncovered child would have
    # to be downloaded, which is exactly what compute_if_no_s3_checksum=False
    # forbids, so the folder is skipped rather than partly fetched.
    s3 = _folder_stub(
        _blake3_child("a.h5ad"), StubObject(key="data/folder/b.h5ad", body=b"bare")
    )

    result = for_assets(
        [_folder_asset()], s3_client=s3, compute_if_no_s3_checksum=False
    )

    assert s3.gets == []
    assert result[0].checksum is None


def test_s3_folder_partial_coverage_caches_the_covered_child_even_when_skipped():
    # The digests resolution did validate are real, and the caller's cache is
    # the only place they survive a skipped folder.
    s3 = _folder_stub(
        _blake3_child("a.h5ad"), StubObject(key="data/folder/b.h5ad", body=b"bare")
    )
    cache = {}

    for_location(
        S3_FOLDER,
        AssetType.folder,
        StoragePlatform.s3,
        None,
        s3,
        cache,
        compute_if_no_s3_checksum=False,
    )

    assert list(cache) == ["s3://bucket/data/folder/a.h5ad"]


def test_s3_folder_partial_coverage_downloads_only_the_uncovered_child():
    s3 = _folder_stub(
        _blake3_child("a.h5ad"), StubObject(key="data/folder/b.h5ad", body=b"bare")
    )

    result = for_assets([_folder_asset()], s3_client=s3, compute_if_no_s3_checksum=True)

    assert s3.gets == ["data/folder/b.h5ad"]
    assert result[0].checksum


def test_s3_folder_explicit_algo_compute_flag_downloads_uncovered_objects():
    s3 = _folder_stub(StubObject(key="data/folder/a.h5ad", body=b"payload"))

    result = for_assets(
        [_folder_asset()],
        algorithm=Algorithm.crc32,
        s3_client=s3,
        compute_if_no_s3_checksum=True,
    )

    assert s3.gets == ["data/folder/a.h5ad"]
    assert result[0].checksum_alg == Algorithm.crc32


def test_s3_folder_explicit_algo_no_compute_flag_skips():
    s3 = _folder_stub(StubObject(key="data/folder/a.h5ad", body=b"payload"))

    result = for_assets(
        [_folder_asset()],
        algorithm=Algorithm.crc32,
        s3_client=s3,
        compute_if_no_s3_checksum=False,
    )

    assert s3.gets == []
    assert result[0].checksum is None


@pytest.mark.parametrize("compute_flag", [True, False])
def test_s3_folder_explicit_algo_matching_children_uses_stored(compute_flag):
    s3 = _folder_stub(
        StubObject(key="data/folder/a.h5ad", body=b"payload").with_native(
            Algorithm.crc32
        )
    )

    result = for_assets(
        [_folder_asset()],
        algorithm=Algorithm.crc32,
        s3_client=s3,
        compute_if_no_s3_checksum=compute_flag,
    )

    assert s3.gets == []
    assert result[0].checksum
    assert result[0].checksum_alg == Algorithm.crc32


def test_an_empty_prefix_still_folds_to_a_digest_when_downloads_are_allowed():
    # An empty prefix is never "complete coverage" — there is nothing to
    # cover — but that must not be confused with a folder that was skipped.
    # With downloads allowed it folds to the empty-folder digest, as before.
    result = for_assets(
        [_folder_asset()], s3_client=StubS3([]), compute_if_no_s3_checksum=True
    )

    assert result[0].checksum


def test_an_empty_prefix_is_skipped_when_downloads_are_disabled():
    result = for_assets(
        [_folder_asset()], s3_client=StubS3([]), compute_if_no_s3_checksum=False
    )

    assert result[0].checksum is None


def test_s3_folder_lists_the_prefix_exactly_once():
    s3 = _folder_stub(_blake3_child("a.h5ad"), _blake3_child("b.h5ad", b"other"))

    for_assets([_folder_asset()], s3_client=s3, compute_if_no_s3_checksum=True)

    assert s3.list_calls == 1


def test_s3_folder_cache_accumulates_across_assets():
    # for_assets shares one dict across its loop, and a folder skipped for
    # incomplete coverage must not drop what an earlier asset contributed.
    first = _blake3_child("a.h5ad")
    second = StubObject(key="data/other/b.h5ad", body=b"bare")
    s3 = StubS3([first, second])
    assets = [
        make_asset(S3_FOLDER, AssetType.folder),
        make_asset("s3://bucket/data/other", AssetType.folder),
    ]

    result = for_assets(assets, s3_client=s3, compute_if_no_s3_checksum=False)

    assert result[0].checksum
    assert result[1].checksum is None


# ── Non-S3 filesystem ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "platform",
    [
        p
        for p in StoragePlatform
        if p is not StoragePlatform.s3 and p not in UNSUPPORTED_PLATFORMS
    ],
)
@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_localfs",
    return_value=make_result(LOCAL_FILE, Algorithm.blake3, HASH),
)
def test_local_file_no_algo_uses_blake3(mock_compute, platform, mock_s3):
    asset = make_asset(LOCAL_FILE, AssetType.file, platform)
    result = for_assets([asset], s3_client=mock_s3)
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.blake3
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.blake3


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_localfs",
    return_value=make_result(LOCAL_FILE, Algorithm.crc32, HASH),
)
def test_local_file_explicit_algo(mock_compute, mock_s3):
    asset = make_asset(LOCAL_FILE, AssetType.file, StoragePlatform.sf_hpc)
    result = for_assets([asset], algorithm=Algorithm.crc32, s3_client=mock_s3)
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.crc32
    assert result[0].checksum_alg == Algorithm.crc32


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_localfs",
    return_value=make_result(LOCAL_FOLDER, Algorithm.blake3, HASH, is_directory=True),
)
def test_local_folder_no_algo_computes_merkle_with_blake3(mock_compute, mock_s3):
    asset = make_asset(LOCAL_FOLDER, AssetType.folder, StoragePlatform.sf_hpc)
    result = for_assets([asset], s3_client=mock_s3)
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.blake3
    assert result[0].checksum == HASH


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_localfs",
    return_value=make_result(LOCAL_FOLDER, Algorithm.crc64, HASH, is_directory=True),
)
def test_local_folder_explicit_algo_computes_merkle(mock_compute, mock_s3):
    asset = make_asset(LOCAL_FOLDER, AssetType.folder, StoragePlatform.sf_hpc)
    result = for_assets([asset], algorithm=Algorithm.crc64, s3_client=mock_s3)
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.crc64
    assert result[0].checksum_alg == Algorithm.crc64


# ── Error / exception ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "exc",
    [Exception("NoCredentialsError"), PermissionError("Access denied")],
    ids=["credential_failure", "file_access_error"],
)
@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={},
)
def test_compute_failure_warns_and_leaves_checksum_unset(mock_fetch, mock_s3, exc):
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate._hash_s3_file", side_effect=exc):
        with pytest.warns(ChecksumWarning, match="Failed to generate checksum"):
            result = for_assets(
                [asset], s3_client=mock_s3, compute_if_no_s3_checksum=True
            )
    assert result[0].checksum is None


@patch("catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums")
@patch("catalog_client.utils.checksum.generate._hash_s3_file")
def test_partial_failure_all_assets_returned(mock_compute, mock_fetch, mock_s3):
    good_uri = S3_FILE
    bad_uri = "s3://bucket/data/bad.h5ad"
    good_result = make_result(good_uri, Algorithm.blake3, HASH)

    mock_fetch.side_effect = [
        {Algorithm.blake3: good_result},  # good asset: stored checksum found
        {},  # bad asset: no stored checksum
    ]
    mock_compute.side_effect = [
        Exception("read failure")
    ]  # compute fails for bad asset

    good_asset = make_asset(good_uri, AssetType.file)
    bad_asset = make_asset(bad_uri, AssetType.file)

    with pytest.warns(ChecksumWarning):
        result = for_assets(
            [good_asset, bad_asset], s3_client=mock_s3, compute_if_no_s3_checksum=True
        )

    assert len(result) == 2
    assert result[0].checksum == HASH
    assert result[1].checksum is None


# ── Caching and s3_client ─────────────────────────────────────────────────────


def test_custom_s3_client_forwarded_to_s3_operations(mock_s3):
    stored = {Algorithm.blake3: make_result(S3_FILE, Algorithm.blake3, HASH)}
    with patch(
        "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
        return_value=stored,
    ) as mock_fetch:
        asset = make_asset(S3_FILE, AssetType.file)
        for_assets([asset], s3_client=mock_s3)
    mock_fetch.assert_called_once_with("bucket", "data/file.h5ad", mock_s3)
    mock_s3.close.assert_not_called()


@pytest.mark.parametrize("cached_algorithm", [Algorithm.crc32, Algorithm.blake3])
def test_fresh_s3_detection_does_not_reuse_stale_file_cache(mock_s3, cached_algorithm):
    mock_s3.head_object.return_value = {}
    mock_s3.get_object.return_value = {"Body": io.BytesIO(b"fresh data")}
    cached = {S3_FILE: make_result(S3_FILE, cached_algorithm)}

    result = for_location(
        S3_FILE,
        AssetType.file,
        StoragePlatform.s3,
        Algorithm.crc32,
        mock_s3,
        cached,
        compute_if_no_s3_checksum=True,
    )

    mock_s3.head_object.assert_called_once()
    mock_s3.get_object.assert_called_once_with(Bucket="bucket", Key="data/file.h5ad")
    assert result.algorithm == Algorithm.crc32
    assert result.value != HASH


def test_fresh_s3_detection_downloads_child_without_current_stored_checksum(mock_s3):
    mock_s3.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "data/folder/file.h5ad", "Size": 10}]}
    ]
    mock_s3.head_object.return_value = {}
    mock_s3.get_object.return_value = {"Body": io.BytesIO(b"fresh data")}

    result = for_location(
        S3_FOLDER,
        AssetType.folder,
        StoragePlatform.s3,
        Algorithm.crc32,
        mock_s3,
        {_CHILD_URI: make_result(_CHILD_URI, Algorithm.crc32)},
        compute_if_no_s3_checksum=True,
    )

    mock_s3.head_object.assert_called_once()
    mock_s3.get_object.assert_called_once_with(
        Bucket="bucket", Key="data/folder/file.h5ad"
    )
    assert result.algorithm == Algorithm.crc32
    assert result.value


@pytest.mark.parametrize(
    "kind", ["empty", "local", "checksummed", "blank", "unsupported"]
)
@patch("catalog_client.utils.checksum.generate.owned_s3_client")
def test_batches_without_s3_work_do_not_create_client(mock_client, kind):
    assets = {
        "empty": [],
        "local": [make_asset(LOCAL_FILE, platform=StoragePlatform.sf_hpc)],
        "checksummed": [make_asset(S3_FILE, checksum=HASH, checksum_alg="blake3")],
        "blank": [make_asset("")],
        "unsupported": [make_asset(LOCAL_FILE, platform=StoragePlatform.other)],
    }[kind]

    with (
        patch(
            "catalog_client.utils.checksum.generate.compute_checksum_localfs",
            return_value=make_result(LOCAL_FILE),
        ),
        warnings.catch_warnings(),
    ):
        warnings.simplefilter("ignore", ChecksumWarning)
        for_assets(assets)

    mock_client.assert_not_called()


@patch("catalog_client.utils.checksum.generate.owned_s3_client")
def test_owned_client_is_created_lazily_reused_and_closed(mock_client):
    client = mock_client.return_value
    assets = [
        make_asset(LOCAL_FILE, platform=StoragePlatform.sf_hpc),
        make_asset(S3_FILE),
        make_asset("s3://bucket/data/second.h5ad"),
    ]

    def compute_local(*args, **kwargs):
        mock_client.assert_not_called()
        return make_result(LOCAL_FILE)

    with (
        patch(
            "catalog_client.utils.checksum.generate.compute_checksum_localfs",
            side_effect=compute_local,
        ),
        patch(
            "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
            return_value={Algorithm.blake3: make_result(S3_FILE)},
        ) as fetch,
    ):
        results = for_assets(assets, s3_workers=3)

    assert len(results) == 3
    mock_client.assert_called_once_with(3, None)
    assert fetch.call_count == 2
    assert all(call.args[2] is client for call in fetch.call_args_list)
    client.close.assert_called_once_with()


@pytest.mark.parametrize("provided", [False, True])
@patch("catalog_client.utils.checksum.generate.owned_s3_client")
def test_client_cleanup_when_a_warning_becomes_an_error(mock_client, provided):
    client = MagicMock() if provided else mock_client.return_value
    with (
        patch(
            "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
            side_effect=OSError("read failed"),
        ),
        warnings.catch_warnings(),
    ):
        warnings.simplefilter("error", ChecksumWarning)
        with pytest.raises(ChecksumWarning, match="read failed"):
            for_assets([make_asset(S3_FILE)], s3_client=client if provided else None)

    if provided:
        mock_client.assert_not_called()
        client.close.assert_not_called()
    else:
        client.close.assert_called_once_with()


# boto3 is imported lazily inside for_assets, so patch the real module attribute
# rather than a name bound on catalog_client.utils.checksum.generate.
@patch("boto3.client")
def test_default_boto3_client_created_when_no_s3_client_passed(mock_client):
    mock_client.return_value = MagicMock()
    stored = {Algorithm.blake3: make_result(S3_FILE, Algorithm.blake3, HASH)}
    with patch(
        "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
        return_value=stored,
    ):
        asset = make_asset(S3_FILE, AssetType.file)
        for_assets([asset])  # no s3_client
    mock_client.assert_called_once()
    assert mock_client.call_args.args == ("s3",)
    # We own this client, so its pool is sized for the concurrent folder scan.
    # Strictly greater, not merely equal: the headroom above the worker budget
    # is what keeps the paginator from contending with a full set of workers,
    # and it is also what keeps an owned client off the clamp warning path.
    config = mock_client.call_args.kwargs["config"]
    assert config.max_pool_connections > DEFAULT_S3_WORKERS


# ── Skip reporting: one mechanism for every skip ─────────────────────────────


@pytest.mark.parametrize(
    "kwargs, why",
    [
        (
            {
                "location_uri": "",
                "asset_type": AssetType.file,
                "storage_platform": StoragePlatform.s3,
            },
            "empty location_uri",
        ),
        (
            {
                "location_uri": S3_FILE,
                "asset_type": AssetType.file,
                "storage_platform": StoragePlatform.other,
            },
            "unsupported platform",
        ),
        (
            {
                "location_uri": S3_FILE,
                "asset_type": AssetType.file,
                "storage_platform": None,
            },
            "missing platform",
        ),
        (
            {
                "location_uri": S3_FILE,
                "asset_type": AssetType.file,
                "storage_platform": StoragePlatform.s3,
                "s3_client": None,
            },
            "no s3_client for an S3 asset",
        ),
    ],
)
def test_every_skip_reason_emits_a_checksum_warning(kwargs, why):
    """A caller escalating ChecksumWarning to an error must catch all of them.

    Previously some skips went to the root logger instead, so
    warnings.simplefilter("error", ChecksumWarning) silently missed them.
    """
    with pytest.warns(ChecksumWarning):
        result = for_location(**kwargs)
    assert not result, why
    assert result.value is None


def test_skips_can_be_escalated_to_exceptions():
    with warnings.catch_warnings():
        warnings.simplefilter("error", ChecksumWarning)
        with pytest.raises(ChecksumWarning):
            for_location(S3_FILE, AssetType.file, StoragePlatform.other)


# ── Input is not mutated ──────────────────────────────────────────────────────


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_localfs",
    return_value=make_result(LOCAL_FILE, Algorithm.blake3, HASH),
)
def test_for_assets_returns_copies_and_leaves_input_untouched(mock_compute, mock_s3):
    asset = make_asset(LOCAL_FILE, AssetType.file, StoragePlatform.sf_hpc)

    result = for_assets([asset], s3_client=mock_s3)

    assert asset.checksum is None, "caller's object must not be modified"
    assert asset.checksum_alg is None
    assert result[0] is not asset
    assert result[0].checksum == HASH


def test_for_assets_preserves_the_concrete_asset_type(mock_s3):
    """model_copy keeps DataAssetResponse a DataAssetResponse."""
    asset = DataAssetResponse(
        location_uri=LOCAL_FILE,
        asset_type=AssetType.file,
        id="asset-1",
        tombstoned=False,
        created_at="2026-01-01T00:00:00Z",
        last_modified_at="2026-01-01T00:00:00Z",
        dataset_id="dataset-1",
    )
    with pytest.warns(ChecksumWarning):
        result = for_assets([asset], s3_client=mock_s3)
    assert isinstance(result[0], DataAssetResponse)


# ── Default algorithm ─────────────────────────────────────────────────────────


@patch("catalog_client.utils.checksum.generate.compute_checksum_localfs")
def test_no_algorithm_uses_the_resolved_default(mock_compute, mock_s3):
    """Not hard-coded blake3: on a base install the default is blake2b."""
    mock_compute.return_value = make_result(LOCAL_FILE, default_algorithm(), HASH)
    asset = make_asset(LOCAL_FILE, AssetType.file, StoragePlatform.sf_hpc)

    for_assets([asset], s3_client=mock_s3)

    assert mock_compute.call_args.kwargs["algorithm"] == default_algorithm()
