"""Unit tests for catalog_client.utils.checksum.generate — for_assets and for_location.

All I/O is mocked; no real files, S3 calls, or network access.
"""

import warnings
from unittest.mock import MagicMock, patch

import pytest

from catalog_client.models.asset import (
    AssetType,
    DataAssetRequest,
    DataAssetResponse,
    StoragePlatform,
)
from catalog_client.utils.checksum.algorithm import Algorithm, default_algorithm
from catalog_client.utils.checksum.generate import (
    UNSUPPORTED_PLATFORMS,
    ChecksumWarning,
    for_assets,
    for_location,
)
from catalog_client.utils.checksum.models import ChecksumResult
from catalog_client.utils.checksum.s3 import _FolderSelection

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
    with patch(
        "catalog_client.utils.checksum.generate.compute_checksum_s3"
    ) as mock_compute:
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=True)
    mock_compute.assert_not_called()
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc64


@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={},
)
@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_s3",
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
    with patch(
        "catalog_client.utils.checksum.generate.compute_checksum_s3"
    ) as mock_compute:
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
    with patch(
        "catalog_client.utils.checksum.generate.compute_checksum_s3"
    ) as mock_compute:
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_not_called()
    assert result[0].checksum is None


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_s3",
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
    with patch(
        "catalog_client.utils.checksum.generate.compute_checksum_s3"
    ) as mock_compute:
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
    with patch(
        "catalog_client.utils.checksum.generate.compute_checksum_s3"
    ) as mock_compute:
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
    with patch(
        "catalog_client.utils.checksum.generate.compute_checksum_s3"
    ) as mock_compute:
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
    "catalog_client.utils.checksum.generate.compute_checksum_s3",
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
    with patch(
        "catalog_client.utils.checksum.generate.compute_checksum_s3"
    ) as mock_compute:
        result = for_assets(
            [asset],
            algorithm=Algorithm.crc32,
            s3_client=mock_s3,
            compute_if_no_s3_checksum=False,
        )
    mock_compute.assert_not_called()
    assert result[0].checksum is None


# ── S3 folder ─────────────────────────────────────────────────────────────────

_CHILD_URI = "s3://bucket/data/folder/file.h5ad"
_CHILD_RESULT = make_result(_CHILD_URI, Algorithm.blake3, HASH)
_FOLDER_RESULT = make_result(S3_FOLDER, Algorithm.blake3, HASH, is_directory=True)


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_s3",
    return_value=_FOLDER_RESULT,
)
@patch(
    "catalog_client.utils.checksum.generate._select_folder_algorithm",
    return_value=_FolderSelection(Algorithm.blake3, {_CHILD_URI: _CHILD_RESULT}, 1),
)
def test_s3_folder_full_coverage_builds_merkle_from_cached_children(
    mock_find, mock_compute, mock_s3
):
    asset = make_asset(S3_FOLDER, AssetType.folder)
    result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=True)
    mock_compute.assert_called_once()
    cached = mock_compute.call_args.kwargs["cached_results"]
    assert _CHILD_URI in cached
    assert result[0].checksum == HASH


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_s3",
    return_value=_FOLDER_RESULT,
)
@patch(
    "catalog_client.utils.checksum.generate._select_folder_algorithm",
    return_value=_FolderSelection(),
)
def test_s3_folder_with_nothing_detectable_falls_back_to_blake3(
    mock_find, mock_compute, mock_s3
):
    asset = make_asset(S3_FOLDER, AssetType.folder)
    result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=True)
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.blake3
    assert result[0].checksum == HASH


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_s3",
    return_value=_FOLDER_RESULT,
)
@patch(
    "catalog_client.utils.checksum.generate._select_folder_algorithm",
    return_value=_FolderSelection(Algorithm.blake3, {_CHILD_URI: _CHILD_RESULT}, 1),
)
def test_s3_folder_auto_detect_no_compute_flag_still_uses_cached_children(
    mock_find, mock_compute, mock_s3
):
    # Every child carries a stored blake3, so assembling the folder digest needs
    # no download and compute_if_no_s3_checksum=False must not block it.
    # Auto-detection must not be worse than naming the algorithm it would pick.
    asset = make_asset(S3_FOLDER, AssetType.folder)
    result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.blake3
    assert _CHILD_URI in mock_compute.call_args.kwargs["cached_results"]
    assert result[0].checksum == HASH


@patch(
    "catalog_client.utils.checksum.generate._select_folder_algorithm",
    return_value=_FolderSelection(Algorithm.blake3, {_CHILD_URI: _CHILD_RESULT}, 1),
)
def test_s3_folder_auto_detect_matches_explicit_algo_under_no_compute_flag(
    mock_find, mock_s3
):
    # Regression guard for the asymmetry itself: algorithm=None and
    # algorithm=blake3 must reach the same outcome when blake3 is what
    # auto-detection finds.
    with patch(
        "catalog_client.utils.checksum.generate.compute_checksum_s3",
        return_value=_FOLDER_RESULT,
    ):
        auto = for_assets(
            [make_asset(S3_FOLDER, AssetType.folder)],
            s3_client=mock_s3,
            compute_if_no_s3_checksum=False,
        )
        explicit = for_assets(
            [make_asset(S3_FOLDER, AssetType.folder)],
            algorithm=Algorithm.blake3,
            s3_client=mock_s3,
            compute_if_no_s3_checksum=False,
        )
    assert auto[0].checksum == explicit[0].checksum
    assert auto[0].checksum_alg == explicit[0].checksum_alg


@patch(
    "catalog_client.utils.checksum.generate._select_folder_algorithm",
    return_value=_FolderSelection(),
)
def test_s3_folder_with_nothing_detectable_no_compute_flag_leaves_checksum_unset(
    mock_find, mock_s3
):
    asset = make_asset(S3_FOLDER, AssetType.folder)
    with patch(
        "catalog_client.utils.checksum.generate.compute_checksum_s3"
    ) as mock_compute:
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_not_called()
    assert result[0].checksum is None


# Two children, one of which carries the algorithm: coverage is real but partial.
_PARTIAL = _FolderSelection(Algorithm.blake3, {_CHILD_URI: _CHILD_RESULT}, 2)


@patch(
    "catalog_client.utils.checksum.generate._select_folder_algorithm",
    return_value=_PARTIAL,
)
def test_s3_folder_partial_coverage_no_compute_flag_skips(mock_find, mock_s3):
    # Partial coverage is not complete coverage. The uncovered child would have
    # to be downloaded, which is exactly what compute_if_no_s3_checksum=False
    # forbids, so the folder is skipped rather than partly fetched.
    asset = make_asset(S3_FOLDER, AssetType.folder)
    with patch(
        "catalog_client.utils.checksum.generate.compute_checksum_s3"
    ) as mock_compute:
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_not_called()
    assert result[0].checksum is None


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_s3",
    return_value=_FOLDER_RESULT,
)
@patch(
    "catalog_client.utils.checksum.generate._select_folder_algorithm",
    return_value=_PARTIAL,
)
def test_s3_folder_partial_coverage_still_reuses_the_covered_children(
    mock_find, mock_compute, mock_s3
):
    # With downloads allowed, the child that already has a digest must still be
    # reused rather than re-fetched — that saving is the point of the change.
    asset = make_asset(S3_FOLDER, AssetType.folder)
    result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=True)
    assert _CHILD_URI in mock_compute.call_args.kwargs["cached_results"]
    assert result[0].checksum == HASH


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_s3",
    return_value=_FOLDER_RESULT,
)
def test_s3_folder_explicit_algo_compute_flag_downloads_all_objects(
    mock_compute, mock_s3
):
    asset = make_asset(S3_FOLDER, AssetType.folder)
    result = for_assets(
        [asset],
        algorithm=Algorithm.crc32,
        s3_client=mock_s3,
        compute_if_no_s3_checksum=True,
    )
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.crc32
    assert result[0].checksum == HASH


def test_s3_folder_explicit_algo_no_compute_flag_skips(mock_s3):
    asset = make_asset(S3_FOLDER, AssetType.folder)
    with patch(
        "catalog_client.utils.checksum.generate.compute_checksum_s3"
    ) as mock_compute:
        result = for_assets(
            [asset],
            algorithm=Algorithm.crc32,
            s3_client=mock_s3,
            compute_if_no_s3_checksum=False,
        )
    mock_compute.assert_not_called()
    assert result[0].checksum is None


_CHILD_RESULT_CRC32 = make_result(_CHILD_URI, Algorithm.crc32, HASH)
_FOLDER_RESULT_CRC32 = make_result(S3_FOLDER, Algorithm.crc32, HASH, is_directory=True)


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_s3",
    return_value=_FOLDER_RESULT_CRC32,
)
@patch(
    "catalog_client.utils.checksum.generate._select_folder_algorithm",
    return_value=_FolderSelection(
        Algorithm.crc32, {_CHILD_URI: _CHILD_RESULT_CRC32}, 1
    ),
)
def test_s3_folder_explicit_algo_matching_children_compute_flag_true_uses_stored(
    mock_find, mock_compute, mock_s3
):
    # Children's shared algo matches explicit — Merkle built from cached children, no download
    asset = make_asset(S3_FOLDER, AssetType.folder)
    result = for_assets(
        [asset],
        algorithm=Algorithm.crc32,
        s3_client=mock_s3,
        compute_if_no_s3_checksum=True,
    )
    mock_compute.assert_called_once()
    assert _CHILD_URI in mock_compute.call_args.kwargs["cached_results"]
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc32


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum_s3",
    return_value=_FOLDER_RESULT_CRC32,
)
@patch(
    "catalog_client.utils.checksum.generate._select_folder_algorithm",
    return_value=_FolderSelection(
        Algorithm.crc32, {_CHILD_URI: _CHILD_RESULT_CRC32}, 1
    ),
)
def test_s3_folder_explicit_algo_matching_children_compute_flag_false_uses_stored(
    mock_find, mock_compute, mock_s3
):
    # compute_if_no_s3_checksum=False does not block Merkle build when children are already cached
    asset = make_asset(S3_FOLDER, AssetType.folder)
    result = for_assets(
        [asset],
        algorithm=Algorithm.crc32,
        s3_client=mock_s3,
        compute_if_no_s3_checksum=False,
    )
    mock_compute.assert_called_once()
    assert _CHILD_URI in mock_compute.call_args.kwargs["cached_results"]
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc32


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
    with patch(
        "catalog_client.utils.checksum.generate.compute_checksum_s3", side_effect=exc
    ):
        with pytest.warns(ChecksumWarning, match="Failed to generate checksum"):
            result = for_assets(
                [asset], s3_client=mock_s3, compute_if_no_s3_checksum=True
            )
    assert result[0].checksum is None


@patch("catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums")
@patch("catalog_client.utils.checksum.generate.compute_checksum_s3")
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
    mock_client.assert_called_once_with("s3")


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
