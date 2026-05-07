"""Unit tests for catalog_client.utils.checksum.generate — for_assets and for_location.

Each test maps to a numbered use case in docs/generate_for_assets_usecases.md.
All I/O is mocked; no real files, S3 calls, or network access.
"""

from unittest.mock import MagicMock, patch

import pytest

from catalog_client.models.asset import AssetType, DataAssetRequest, StoragePlatform
from catalog_client.utils.checksum.algorithm import Algorithm
from catalog_client.utils.checksum.generate import ChecksumWarning, for_assets
from catalog_client.utils.checksum.models import ChecksumResult

# ── Helpers ──────────────────────────────────────────────────────────────────

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


# ── UC-1 & UC-2: Input-level ──────────────────────────────────────────────────


def test_empty_asset_list_returns_empty(mock_s3):
    # UC-1
    assert for_assets([], s3_client=mock_s3) == []


def test_asset_with_existing_checksum_passed_through_unchanged(mock_s3):
    # UC-2: asset already has checksum — returned as-is, for_location never called
    asset = make_asset(S3_FILE, checksum="existing_hash", checksum_alg="blake3")
    with patch("catalog_client.utils.checksum.generate.for_location") as mock_fl:
        result = for_assets([asset], s3_client=mock_s3)
    mock_fl.assert_not_called()
    assert result[0].checksum == "existing_hash"
    assert result[0].checksum_alg == "blake3"


# ── UC-3, UC-4, UC-5: Unsupported platforms ───────────────────────────────────


@pytest.mark.parametrize(
    "platform",
    [None, StoragePlatform.external, StoragePlatform.other],
    ids=["none", "external", "other"],
)
def test_unsupported_platform_warns_and_leaves_checksum_unset(mock_s3, platform):
    # UC-3 (None), UC-4 (external), UC-5 (other)
    asset = make_asset(LOCAL_FILE, asset_type=AssetType.file, platform=platform)
    with pytest.warns(ChecksumWarning):
        result = for_assets([asset], s3_client=mock_s3)
    assert result[0].checksum is None
    assert result[0].checksum_alg is None


# ── UC-6 – UC-11: S3 file ─────────────────────────────────────────────────────


@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={Algorithm.crc64: make_result(S3_FILE, Algorithm.crc64, HASH)},
)
def test_s3_file_stored_checksum_returned_without_download(mock_fetch, mock_s3):
    # UC-6: algorithm=None, compute_if_no_s3_checksum=True, stored checksum found
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate.compute_checksum") as mock_compute:
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=True)
    mock_compute.assert_not_called()
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc64


@patch("catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums", return_value={})
@patch(
    "catalog_client.utils.checksum.generate.compute_checksum",
    return_value=make_result(S3_FILE, Algorithm.blake3, HASH),
)
def test_s3_file_no_stored_checksum_falls_back_to_blake3(mock_compute, mock_fetch, mock_s3):
    # UC-7: algorithm=None, compute_if_no_s3_checksum=True, no stored → fallback blake3
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
    # UC-8: algorithm=None, compute_if_no_s3_checksum=False, stored checksum found
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate.compute_checksum") as mock_compute:
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_not_called()
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc32


@patch("catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums", return_value={})
def test_s3_file_no_stored_no_compute_flag_leaves_checksum_unset(mock_fetch, mock_s3):
    # UC-9: algorithm=None, compute_if_no_s3_checksum=False, no stored → unset
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate.compute_checksum") as mock_compute:
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_not_called()
    assert result[0].checksum is None


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum",
    return_value=make_result(S3_FILE, Algorithm.crc32, HASH),
)
def test_s3_file_explicit_algo_with_compute_flag_downloads_and_computes(mock_compute, mock_s3):
    # UC-10: explicit algorithm, compute_if_no_s3_checksum=True → downloads and computes
    asset = make_asset(S3_FILE, AssetType.file)
    result = for_assets([asset], algorithm=Algorithm.crc32, s3_client=mock_s3, compute_if_no_s3_checksum=True)
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.crc32
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc32


def test_s3_file_explicit_algo_no_compute_flag_skips_download(mock_s3):
    # UC-11: explicit algorithm, compute_if_no_s3_checksum=False → download skipped, unset
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate.compute_checksum") as mock_compute:
        result = for_assets([asset], algorithm=Algorithm.crc32, s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_not_called()
    assert result[0].checksum is None


# ── UC-28 – UC-31: S3 file, explicit algorithm, stored checksum present ───────


@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={Algorithm.crc32: make_result(S3_FILE, Algorithm.crc32, HASH)},
)
def test_s3_file_explicit_algo_matching_stored_compute_flag_true_uses_stored(mock_fetch, mock_s3):
    # UC-28: explicit algorithm, compute_if_no_s3_checksum=True, stored algo matches → use stored, don't compute
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate.compute_checksum") as mock_compute:
        result = for_assets([asset], algorithm=Algorithm.crc32, s3_client=mock_s3, compute_if_no_s3_checksum=True)
    mock_compute.assert_not_called()
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc32


@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={Algorithm.crc32: make_result(S3_FILE, Algorithm.crc32, HASH)},
)
def test_s3_file_explicit_algo_matching_stored_compute_flag_false_uses_stored(mock_fetch, mock_s3):
    # UC-29: explicit algorithm, compute_if_no_s3_checksum=False, stored algo matches → use stored, don't compute
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate.compute_checksum") as mock_compute:
        result = for_assets([asset], algorithm=Algorithm.crc32, s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_not_called()
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc32


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum",
    return_value=make_result(S3_FILE, Algorithm.crc32, HASH),
)
@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={Algorithm.blake3: make_result(S3_FILE, Algorithm.blake3, HASH)},
)
def test_s3_file_explicit_algo_mismatched_stored_compute_flag_true_downloads_and_computes(
    mock_fetch, mock_compute, mock_s3
):
    # UC-30: explicit algorithm, compute_if_no_s3_checksum=True, stored algo does not match → download and compute
    asset = make_asset(S3_FILE, AssetType.file)
    result = for_assets([asset], algorithm=Algorithm.crc32, s3_client=mock_s3, compute_if_no_s3_checksum=True)
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.crc32
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.crc32


@patch(
    "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
    return_value={Algorithm.blake3: make_result(S3_FILE, Algorithm.blake3, HASH)},
)
def test_s3_file_explicit_algo_mismatched_stored_compute_flag_false_leaves_checksum_unset(mock_fetch, mock_s3):
    # UC-31: explicit algorithm, compute_if_no_s3_checksum=False, stored algo does not match → unset, skip download
    asset = make_asset(S3_FILE, AssetType.file)
    with patch("catalog_client.utils.checksum.generate.compute_checksum") as mock_compute:
        result = for_assets([asset], algorithm=Algorithm.crc32, s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_not_called()
    assert result[0].checksum is None


# ── UC-12 – UC-17: S3 folder ──────────────────────────────────────────────────

_CHILD_URI = "s3://bucket/data/folder/file.h5ad"
_CHILD_RESULT = make_result(_CHILD_URI, Algorithm.blake3, HASH)
_FOLDER_RESULT = make_result(S3_FOLDER, Algorithm.blake3, HASH, is_directory=True)


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum",
    return_value=_FOLDER_RESULT,
)
@patch(
    "catalog_client.utils.checksum.generate._find_common_algorithm_in_folder",
    return_value=(Algorithm.blake3, {_CHILD_URI: _CHILD_RESULT}),
)
def test_s3_folder_common_algo_builds_merkle_from_cached_children(mock_find, mock_compute, mock_s3):
    # UC-12: algorithm=None, compute_if_no_s3_checksum=True, common algo found
    asset = make_asset(S3_FOLDER, AssetType.folder)
    result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=True)
    mock_compute.assert_called_once()
    cached = mock_compute.call_args.kwargs["cached_results"]
    assert _CHILD_URI in cached
    assert result[0].checksum == HASH


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum",
    return_value=_FOLDER_RESULT,
)
@patch(
    "catalog_client.utils.checksum.generate._find_common_algorithm_in_folder",
    return_value=(None, {}),
)
def test_s3_folder_no_common_algo_falls_back_to_blake3(mock_find, mock_compute, mock_s3):
    # UC-13: algorithm=None, compute_if_no_s3_checksum=True, no common algo → fallback blake3
    asset = make_asset(S3_FOLDER, AssetType.folder)
    result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=True)
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.blake3
    assert result[0].checksum == HASH


@patch(
    "catalog_client.utils.checksum.generate._find_common_algorithm_in_folder",
    return_value=(Algorithm.blake3, {_CHILD_URI: _CHILD_RESULT}),
)
def test_s3_folder_common_algo_no_compute_flag_leaves_checksum_unset(mock_find, mock_s3):
    # UC-14: algorithm=None, compute_if_no_s3_checksum=False, common algo found
    # Folder URI itself is not in cached_results, so compute would be required
    # but compute_if_no_s3_checksum=False prevents it → checksum unset
    asset = make_asset(S3_FOLDER, AssetType.folder)
    with patch("catalog_client.utils.checksum.generate.compute_checksum") as mock_compute:
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_not_called()
    assert result[0].checksum is None


@patch(
    "catalog_client.utils.checksum.generate._find_common_algorithm_in_folder",
    return_value=(None, {}),
)
def test_s3_folder_no_common_algo_no_compute_flag_leaves_checksum_unset(mock_find, mock_s3):
    # UC-15: algorithm=None, compute_if_no_s3_checksum=False, no common algo → unset
    asset = make_asset(S3_FOLDER, AssetType.folder)
    with patch("catalog_client.utils.checksum.generate.compute_checksum") as mock_compute:
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_not_called()
    assert result[0].checksum is None


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum",
    return_value=_FOLDER_RESULT,
)
def test_s3_folder_explicit_algo_compute_flag_downloads_all_objects(mock_compute, mock_s3):
    # UC-16: explicit algorithm, compute_if_no_s3_checksum=True → downloads and computes
    asset = make_asset(S3_FOLDER, AssetType.folder)
    result = for_assets([asset], algorithm=Algorithm.crc32, s3_client=mock_s3, compute_if_no_s3_checksum=True)
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.crc32
    assert result[0].checksum == HASH


def test_s3_folder_explicit_algo_no_compute_flag_skips(mock_s3):
    # UC-17: explicit algorithm, compute_if_no_s3_checksum=False → skipped, unset
    asset = make_asset(S3_FOLDER, AssetType.folder)
    with patch("catalog_client.utils.checksum.generate.compute_checksum") as mock_compute:
        result = for_assets([asset], algorithm=Algorithm.crc32, s3_client=mock_s3, compute_if_no_s3_checksum=False)
    mock_compute.assert_not_called()
    assert result[0].checksum is None


# ── UC-18 – UC-21: Non-S3 filesystem ─────────────────────────────────────────


@pytest.mark.parametrize(
    "platform",
    [StoragePlatform.hpc, StoragePlatform.bruno_hpc, StoragePlatform.coreweave],
)
@patch(
    "catalog_client.utils.checksum.generate.compute_checksum",
    return_value=make_result(LOCAL_FILE, Algorithm.blake3, HASH),
)
def test_local_file_no_algo_uses_blake3(mock_compute, platform, mock_s3):
    # UC-18: non-S3 file, algorithm=None → computes with blake3
    asset = make_asset(LOCAL_FILE, AssetType.file, platform)
    result = for_assets([asset], s3_client=mock_s3)
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.blake3
    assert result[0].checksum == HASH
    assert result[0].checksum_alg == Algorithm.blake3


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum",
    return_value=make_result(LOCAL_FILE, Algorithm.crc32, HASH),
)
def test_local_file_explicit_algo(mock_compute, mock_s3):
    # UC-19: non-S3 file, explicit algorithm → computes with that algorithm
    asset = make_asset(LOCAL_FILE, AssetType.file, StoragePlatform.hpc)
    result = for_assets([asset], algorithm=Algorithm.crc32, s3_client=mock_s3)
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.crc32
    assert result[0].checksum_alg == Algorithm.crc32


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum",
    return_value=make_result(LOCAL_FOLDER, Algorithm.blake3, HASH, is_directory=True),
)
def test_local_folder_no_algo_computes_merkle_with_blake3(mock_compute, mock_s3):
    # UC-20: non-S3 folder, algorithm=None → Merkle tree with blake3
    asset = make_asset(LOCAL_FOLDER, AssetType.folder, StoragePlatform.hpc)
    result = for_assets([asset], s3_client=mock_s3)
    mock_compute.assert_called_once()
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.blake3
    assert result[0].checksum == HASH


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum",
    return_value=make_result(LOCAL_FOLDER, Algorithm.crc64, HASH, is_directory=True),
)
def test_local_folder_explicit_algo_computes_merkle(mock_compute, mock_s3):
    # UC-21: non-S3 folder, explicit algorithm → Merkle tree with that algorithm
    asset = make_asset(LOCAL_FOLDER, AssetType.folder, StoragePlatform.hpc)
    result = for_assets([asset], algorithm=Algorithm.crc64, s3_client=mock_s3)
    assert mock_compute.call_args.kwargs["algorithm"] == Algorithm.crc64
    assert result[0].checksum_alg == Algorithm.crc64


# ── UC-22 – UC-24: Error / exception ─────────────────────────────────────────


@patch("catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums", return_value={})
@patch("catalog_client.utils.checksum.generate.compute_checksum", side_effect=Exception("NoCredentialsError"))
def test_s3_credential_failure_warns_and_leaves_checksum_unset(mock_compute, mock_fetch, mock_s3):
    # UC-22: S3 asset, credentials error on compute → ChecksumWarning, checksum unset
    asset = make_asset(S3_FILE, AssetType.file)
    with pytest.warns(ChecksumWarning, match="Failed to generate checksum"):
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=True)
    assert result[0].checksum is None


@patch("catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums", return_value={})
@patch("catalog_client.utils.checksum.generate.compute_checksum", side_effect=PermissionError("Access denied"))
def test_file_access_error_warns_and_leaves_checksum_unset(mock_compute, mock_fetch, mock_s3):
    # UC-23: read error or access denied → ChecksumWarning, checksum unset
    asset = make_asset(S3_FILE, AssetType.file)
    with pytest.warns(ChecksumWarning, match="Failed to generate checksum"):
        result = for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=True)
    assert result[0].checksum is None


@patch("catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums")
@patch("catalog_client.utils.checksum.generate.compute_checksum")
def test_partial_failure_all_assets_returned(mock_compute, mock_fetch, mock_s3):
    # UC-24: multiple assets, some fail — all returned; failures warn, successes get checksum
    good_uri = S3_FILE
    bad_uri = "s3://bucket/data/bad.h5ad"
    good_result = make_result(good_uri, Algorithm.blake3, HASH)

    mock_fetch.side_effect = [
        {Algorithm.blake3: good_result},  # good asset: stored checksum found
        {},  # bad asset: no stored checksum
    ]
    mock_compute.side_effect = [Exception("read failure")]  # compute fails for bad asset

    good_asset = make_asset(good_uri, AssetType.file)
    bad_asset = make_asset(bad_uri, AssetType.file)

    with pytest.warns(ChecksumWarning):
        result = for_assets([good_asset, bad_asset], s3_client=mock_s3, compute_if_no_s3_checksum=True)

    assert len(result) == 2
    assert result[0].checksum == HASH
    assert result[1].checksum is None


# ── UC-25 – UC-27: Caching and s3_client ─────────────────────────────────────


@patch(
    "catalog_client.utils.checksum.generate.compute_checksum",
    return_value=_FOLDER_RESULT,
)
@patch(
    "catalog_client.utils.checksum.generate._find_common_algorithm_in_folder",
    return_value=(Algorithm.blake3, {_CHILD_URI: _CHILD_RESULT}),
)
def test_folder_children_added_to_cached_results_for_compute(mock_find, mock_compute, mock_s3):
    # UC-25: cached_results populated with children from detection phase
    # so compute_checksum receives them and avoids re-fetching
    asset = make_asset(S3_FOLDER, AssetType.folder)
    for_assets([asset], s3_client=mock_s3, compute_if_no_s3_checksum=True)
    cached = mock_compute.call_args.kwargs["cached_results"]
    assert _CHILD_URI in cached


def test_custom_s3_client_forwarded_to_s3_operations(mock_s3):
    # UC-26: custom s3_client is passed through to all S3 calls
    stored = {Algorithm.blake3: make_result(S3_FILE, Algorithm.blake3, HASH)}
    with patch(
        "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
        return_value=stored,
    ) as mock_fetch:
        asset = make_asset(S3_FILE, AssetType.file)
        for_assets([asset], s3_client=mock_s3)
    # s3_client is the third positional arg: (bucket, key, s3_client)
    assert mock_fetch.call_args.args[2] is mock_s3


@patch("catalog_client.utils.checksum.generate.boto3")
def test_default_boto3_client_created_when_no_s3_client_passed(mock_boto3):
    # UC-27: s3_client=None → boto3.client("s3") created automatically
    mock_boto3.client.return_value = MagicMock()
    stored = {Algorithm.blake3: make_result(S3_FILE, Algorithm.blake3, HASH)}
    with patch("catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums", return_value=stored):
        asset = make_asset(S3_FILE, AssetType.file)
        for_assets([asset])  # no s3_client
    mock_boto3.client.assert_called_once_with("s3")
