"""Tests for checksum utilities module.

These are integration-level tests: the S3 cases drive real boto3 request/response
shapes through moto, so they cover the wiring that tests/utils/checksum/test_generate.py
deliberately mocks out (metadata key casing, HeadObject response fields, error types).
"""

import hashlib
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

from catalog_client.models.asset import AssetType, DataAssetRequest, StoragePlatform
from catalog_client.utils import checksum as checksums
from catalog_client.utils.checksum.algorithm import DIGEST_HEX_LENGTH, Algorithm
from catalog_client.utils.checksum.s3 import (
    _fetch_all_s3_stored_checksums,
    _parse_s3_uri,
    _select_best_algorithm,
    _select_folder_algorithm,
)

BUCKET = "test-bucket"


def hex64(seed: str) -> str:
    """A distinct but well-formed 64-char (blake3-width) hex digest.

    Stored checksums must be hex of the algorithm's exact width — placeholder
    strings like "hash_b3" are rejected at read time — so tests that only need
    "some digest" derive one deterministically from a label.
    """
    return hashlib.blake2b(seed.encode(), digest_size=32).hexdigest()


def hex_for(seed: str, algorithm: Algorithm) -> str:
    """A well-formed digest of the right width for `algorithm`."""
    width = DIGEST_HEX_LENGTH[algorithm]
    return hashlib.blake2b(seed.encode(), digest_size=width // 2).hexdigest()


@pytest.fixture
def s3():
    """A moto-backed S3 client with the test bucket already created.

    The mock_aws context is held open by the fixture rather than applied as a class
    decorator, so that bucket setup and the test body share one mocked session.
    """
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def make_asset(uri, asset_type=AssetType.file, platform=StoragePlatform.s3, **kwargs):
    return DataAssetRequest(
        location_uri=uri, asset_type=asset_type, storage_platform=platform, **kwargs
    )


# ── URI Parsing ────────────────────────────────────────────────────────────────


class TestParseS3Uri:
    @pytest.mark.parametrize(
        "uri, expected_bucket, expected_key",
        [
            ("s3://my-bucket/path/to/key", "my-bucket", "path/to/key"),
            ("s3a://my-bucket/path/to/key", "my-bucket", "path/to/key"),
            ("s3://my-bucket/", "my-bucket", ""),
            ("s3://my-bucket", "my-bucket", ""),
        ],
    )
    def test_valid_uris(self, uri, expected_bucket, expected_key):
        bucket, key = _parse_s3_uri(uri)
        assert bucket == expected_bucket
        assert key == expected_key

    def test_invalid_uri_raises(self):
        with pytest.raises(ValueError, match="Not an S3 URI"):
            _parse_s3_uri("http://example.com/file")


# ── Algorithm Selection ────────────────────────────────────────────────────────


class TestSelectBestAlgorithm:
    @pytest.mark.parametrize(
        "algorithms, expected",
        [
            ({"blake3", "crc32"}, "blake3"),
            ({"crc32", "crc64nvme"}, "crc64nvme"),
            ({"crc32"}, "crc32"),
            ({"blake2b", "crc64"}, "blake2b"),
            ({"blake3", "blake2b", "crc64", "crc64nvme", "crc32"}, "blake3"),
            (set(), None),
        ],
    )
    def test_priority_selection(self, algorithms, expected):
        assert _select_best_algorithm(algorithms) == expected


# ── S3 Stored Checksum Fetching ────────────────────────────────────────────────


class TestFetchAllS3StoredChecksums:
    def test_no_metadata_checksums(self, s3):
        s3.put_object(Bucket=BUCKET, Key="plain.txt", Body=b"data")

        result = _fetch_all_s3_stored_checksums(BUCKET, "plain.txt", s3)
        for algo in ["blake3", "blake2b", "crc64"]:
            assert algo not in result

    def test_metadata_checksums_with_merkle(self, s3):
        file_hash, merkle = hex64("file"), hex64("merkle")
        s3.put_object(
            Bucket=BUCKET,
            Key="meta.txt",
            Body=b"data",
            Metadata={
                "x-checksum-blake3": file_hash,
                "x-checksum-blake3-merkle": merkle,
            },
        )

        result = _fetch_all_s3_stored_checksums(BUCKET, "meta.txt", s3)
        assert result["blake3"].file_hash == file_hash
        assert result["blake3"].merkle_root == merkle
        assert result["blake3"].source == "s3_metadata"

    def test_metadata_without_merkle_uses_file_hash(self, s3):
        digest = hex_for("crc64-value", Algorithm.crc64)
        s3.put_object(
            Bucket=BUCKET,
            Key="meta.txt",
            Body=b"data",
            Metadata={"x-checksum-crc64": digest},
        )

        result = _fetch_all_s3_stored_checksums(BUCKET, "meta.txt", s3)
        assert result["crc64"].merkle_root == digest

    def test_nonexistent_object_returns_empty(self, s3):
        assert _fetch_all_s3_stored_checksums(BUCKET, "missing.txt", s3) == {}

    def test_multiple_metadata_algorithms(self, s3):
        s3.put_object(
            Bucket=BUCKET,
            Key="multi.txt",
            Body=b"data",
            Metadata={
                "x-checksum-blake3": hex_for("b3", Algorithm.blake3),
                "x-checksum-blake2b": hex_for("b2", Algorithm.blake2b),
            },
        )

        result = _fetch_all_s3_stored_checksums(BUCKET, "multi.txt", s3)
        assert "blake3" in result
        assert "blake2b" in result

    @pytest.mark.parametrize(
        "bad_value, why",
        [
            ("not-hex-at-all", "non-hex characters"),
            ("aabb", "hex but far too short for blake3"),
            ("aa" * 64, "hex but too long for blake3"),
        ],
    )
    def test_malformed_metadata_digest_is_ignored(self, s3, bad_value, why):
        """A stored value that is not a well-formed digest is not usable.

        It could not be packed into a parent folder's Merkle root, so admitting
        it would make a file's checksum depend on whether it was hashed alone
        or as a folder child. It is dropped at read time instead.
        """
        s3.put_object(
            Bucket=BUCKET,
            Key="bad.txt",
            Body=b"data",
            Metadata={"x-checksum-blake3": bad_value},
        )

        result = _fetch_all_s3_stored_checksums(BUCKET, "bad.txt", s3)
        assert "blake3" not in result, why

    def test_one_bad_value_does_not_discard_the_others(self, s3):
        """A single unreadable checksum must not hide the object's good ones."""
        good = hex_for("b2", Algorithm.blake2b)
        s3.put_object(
            Bucket=BUCKET,
            Key="mixed.txt",
            Body=b"data",
            Metadata={
                "x-checksum-blake3": "garbage",
                "x-checksum-blake2b": good,
            },
        )

        result = _fetch_all_s3_stored_checksums(BUCKET, "mixed.txt", s3)
        assert "blake3" not in result
        assert result["blake2b"].file_hash == good

    def test_non_missing_error_is_raised_not_swallowed(self, s3):
        """An access error is a real problem, not "this object has no checksum".

        Swallowing it would silently trigger a full download, or a silent skip
        under compute_if_no_s3_checksum=False.
        """
        with pytest.raises(Exception, match="NoSuchBucket|AccessDenied|404"):
            _fetch_all_s3_stored_checksums("no-such-bucket-here", "k.txt", s3)


# ── Folder Algorithm Selection ─────────────────────────────────────────────────


def _put(s3, key, body=b"data", *, native="SHA256", **metadata):
    """Put an object, controlling which native checksum S3 attaches to it.

    moto — like S3 itself now does — attaches a native checksum to every
    upload, so "this object carries only a blake3" has to be stated rather
    than assumed. SHA256 is not one of the algorithms this library reads
    (see _S3_NATIVE_RESPONSE_KEY), so it stands in for "no usable native
    checksum" without having to defeat the platform's default.
    """
    s3.put_object(
        Bucket=BUCKET, Key=key, Body=body, ChecksumAlgorithm=native, Metadata=metadata
    )


class TestSelectFolderAlgorithm:
    """Selection ranks algorithms by how much recompute each would cost.

    The property under test throughout is that a child without a stored
    checksum costs one download, never the whole folder. The predecessor of
    this function required an algorithm common to every child, so one
    checksumless object in a 100k-object prefix discarded 99,999 usable
    digests and re-downloaded everything.
    """

    def test_full_coverage_selects_that_algorithm_and_caches_every_child(self, s3):
        for name in ["a.txt", "b.txt", "c.txt"]:
            _put(s3, f"dataset/{name}", **{"x-checksum-blake3": hex64(name)})

        selection = _select_folder_algorithm(f"s3://{BUCKET}/dataset/", s3)
        assert selection.algorithm == Algorithm.blake3
        assert len(selection.cached) == 3
        assert selection.total_children == 3

    def test_one_checksumless_child_keeps_every_other_stored_digest(self, s3):
        # The regression this whole change exists for.
        for name in ["a.txt", "b.txt", "c.txt"]:
            _put(s3, f"dataset/{name}", **{"x-checksum-blake3": hex64(name)})
        _put(s3, "dataset/d.txt")  # no checksum at all

        selection = _select_folder_algorithm(f"s3://{BUCKET}/dataset/", s3)
        assert selection.algorithm == Algorithm.blake3
        assert len(selection.cached) == 3  # not 0
        assert selection.total_children == 4

    def test_full_coverage_beats_partial_coverage(self, s3):
        # a has {blake3, crc64}, b has {crc64}: crc64 needs no downloads at all,
        # blake3 would need one. Cost decides, not the priority table.
        _put(
            s3,
            "dataset/a.txt",
            **{
                "x-checksum-blake3": hex_for("b3", Algorithm.blake3),
                "x-checksum-crc64": hex_for("c64-a", Algorithm.crc64),
            },
        )
        _put(
            s3,
            "dataset/b.txt",
            **{"x-checksum-crc64": hex_for("c64-b", Algorithm.crc64)},
        )

        selection = _select_folder_algorithm(f"s3://{BUCKET}/dataset/", s3)
        assert selection.algorithm == Algorithm.crc64
        assert len(selection.cached) == 2

    def test_selection_follows_bytes_when_counts_are_equal(self, s3):
        # Each algorithm covers exactly one of the two objects, so only the
        # size of what is left decides: picking blake3 means downloading 4MB,
        # picking crc32 means downloading one byte.
        _put(s3, "dataset/big.bin", b"x" * 4_000_000, native="CRC32")
        _put(s3, "dataset/small.bin", b"x", **{"x-checksum-blake3": hex64("b3")})

        selection = _select_folder_algorithm(f"s3://{BUCKET}/dataset/", s3)
        assert selection.algorithm == Algorithm.crc32

    def test_selection_follows_object_count_when_bytes_are_equal(self, s3):
        # Both options leave 20,000 bytes to fetch. crc32 leaves them in one
        # object, blake3 in twenty. Round trips are the only difference, which
        # is the half of the cost model that bytes alone would miss.
        for i in range(20):
            _put(s3, f"dataset/many-{i:02d}.bin", b"x" * 1_000, native="CRC32")
        _put(s3, "dataset/one.bin", b"x" * 20_000, **{"x-checksum-blake3": hex64("b3")})

        selection = _select_folder_algorithm(f"s3://{BUCKET}/dataset/", s3)
        assert selection.algorithm == Algorithm.crc32
        assert len(selection.cached) == 20

    def test_priority_breaks_ties_when_recompute_is_equal(self, s3):
        # Every child carries both, so neither needs a download and the cost
        # model cannot separate them. Only then does the priority table decide.
        for name in ["a.txt", "b.txt"]:
            _put(
                s3,
                f"dataset/{name}",
                native="CRC32",
                **{"x-checksum-blake3": hex64(name)},
            )

        selection = _select_folder_algorithm(f"s3://{BUCKET}/dataset/", s3)
        assert selection.algorithm == Algorithm.blake3
        assert len(selection.cached) == 2

    def test_no_child_has_a_checksum_falls_back_to_the_default(self, s3):
        _put(s3, "dataset/a.txt")
        _put(s3, "dataset/b.txt")

        selection = _select_folder_algorithm(f"s3://{BUCKET}/dataset/", s3)
        assert selection.algorithm == checksums.default_algorithm()
        assert selection.cached == {}
        assert selection.total_children == 2

    def test_an_algorithm_this_install_cannot_compute_is_never_selected(
        self, s3, monkeypatch
    ):
        # Combining children into a folder digest needs a working hasher, so an
        # algorithm S3 stored but that this install cannot build would fail
        # partway through the walk rather than at selection time.
        for name in ["a.txt", "b.txt"]:
            _put(
                s3,
                f"dataset/{name}",
                **{"x-checksum-crc64": hex_for(name, Algorithm.crc64)},
            )
        monkeypatch.setattr(
            "catalog_client.utils.checksum.s3.available_algorithms",
            lambda: {Algorithm.blake3, Algorithm.blake2b, Algorithm.crc32},
        )

        selection = _select_folder_algorithm(f"s3://{BUCKET}/dataset/", s3)
        assert selection.algorithm != Algorithm.crc64
        assert selection.cached == {}

    def test_an_explicit_algorithm_skips_selection_but_still_reuses_children(self, s3):
        # Naming an algorithm used to discard every cached child unless all of
        # them carried it. The children that do carry it are still reusable.
        _put(s3, "dataset/a.txt", native="CRC32")
        _put(s3, "dataset/b.txt")  # no algorithm this library reads

        selection = _select_folder_algorithm(
            f"s3://{BUCKET}/dataset/", s3, Algorithm.crc32
        )
        assert selection.algorithm == Algorithm.crc32
        assert list(selection.cached) == [f"s3://{BUCKET}/dataset/a.txt"]
        assert selection.total_children == 2

    def test_empty_folder_selects_nothing(self, s3):
        selection = _select_folder_algorithm(f"s3://{BUCKET}/empty/", s3)
        assert selection.algorithm is None
        assert selection.cached == {}
        assert selection.total_children == 0

    def test_empty_folder_passes_an_explicit_algorithm_through(self, s3):
        selection = _select_folder_algorithm(
            f"s3://{BUCKET}/empty/", s3, Algorithm.crc32
        )
        assert selection.algorithm == Algorithm.crc32
        assert selection.total_children == 0

    def test_local_path_selects_nothing(self):
        selection = _select_folder_algorithm("/local/path", None)
        assert selection.algorithm is None
        assert selection.cached == {}


# ── for_assets: Core Behaviors ─────────────────────────────────────────────────


class TestGenerateForAssetsCore:
    def test_empty_list(self):
        assert checksums.for_assets([]) == []

    def test_skips_assets_with_existing_checksums(self):
        assets = [
            make_asset(
                "/hpc/existing.txt",
                platform=StoragePlatform.sf_hpc,
                checksum="existing123",
                checksum_alg="blake3",
            )
        ]
        result = checksums.for_assets(assets, algorithm="crc32")
        assert result[0].checksum == "existing123"
        assert result[0].checksum_alg == "blake3"

    def test_unsupported_platform_warns_and_preserves_asset(self):
        assets = [
            make_asset("http://example.com/file.txt", platform=StoragePlatform.other)
        ]
        with pytest.warns(checksums.ChecksumWarning, match="not supported") as rec:
            result = checksums.for_assets(assets, algorithm="blake3")
        assert len(rec) == 1
        assert result[0].checksum is None


# ── for_assets: Filesystem ─────────────────────────────────────────────────────


class TestGenerateForAssetsFilesystem:
    @pytest.mark.parametrize(
        "algorithm, expected_hex_len",
        [
            ("blake3", 64),
            ("blake2b", 128),
            ("crc32", 8),
        ],
    )
    def test_local_file_with_algorithm(self, tmp_path, algorithm, expected_hex_len):
        target = tmp_path / "file.txt"
        target.write_text("test content")

        assets = [make_asset(str(target), platform=StoragePlatform.sf_hpc)]
        result = checksums.for_assets(assets, algorithm=algorithm)
        assert result[0].checksum_alg == algorithm
        assert len(result[0].checksum) == expected_hex_len

    def test_local_directory(self, tmp_path):
        for name in ["a.txt", "b.txt"]:
            (tmp_path / name).write_text(f"content_{name}")

        assets = [
            make_asset(
                str(tmp_path),
                asset_type=AssetType.folder,
                platform=StoragePlatform.sf_hpc,
            )
        ]
        result = checksums.for_assets(assets, algorithm="blake3")
        assert result[0].checksum is not None
        assert result[0].checksum_alg == "blake3"

    def test_nonexistent_file_warns(self):
        assets = [make_asset("/nonexistent/file.txt", platform=StoragePlatform.sf_hpc)]
        with pytest.warns(
            checksums.ChecksumWarning, match="Failed to generate checksum"
        ) as rec:
            result = checksums.for_assets(assets, algorithm="blake3")
        assert len(rec) == 1
        assert result[0].checksum is None

    def test_none_algorithm_defaults_to_blake3(self, tmp_path):
        target = tmp_path / "file.txt"
        target.write_text("test")

        assets = [make_asset(str(target), platform=StoragePlatform.sf_hpc)]
        result = checksums.for_assets(assets, algorithm=None)
        assert result[0].checksum_alg == "blake3"


# ── for_assets: S3 Integration ─────────────────────────────────────────────────


class TestGenerateForAssetsS3:
    def test_explicit_algorithm(self, s3):
        s3.put_object(Bucket=BUCKET, Key="file.txt", Body=b"data")

        assets = [make_asset(f"s3://{BUCKET}/file.txt")]
        result = checksums.for_assets(assets, algorithm="blake3", s3_client=s3)
        assert result[0].checksum_alg == "blake3"
        assert result[0].checksum is not None

    def test_auto_detect_file_uses_stored_metadata(self, s3):
        """algorithm=None on S3 file with metadata -> uses stored checksum.

        Covers real S3 metadata key casing: S3 lowercases user metadata keys, which
        the s3.py lookup depends on.
        """
        stored = hex_for("stored", Algorithm.blake3)
        s3.put_object(
            Bucket=BUCKET,
            Key="file.txt",
            Body=b"data",
            Metadata={"x-checksum-blake3": stored},
        )

        assets = [make_asset(f"s3://{BUCKET}/file.txt")]
        result = checksums.for_assets(assets, algorithm=None, s3_client=s3)
        assert result[0].checksum == stored
        assert result[0].checksum_alg == "blake3"

    def test_auto_detect_file_falls_back_to_blake3(self, s3, monkeypatch):
        """algorithm=None on S3 file with no stored checksums -> computes blake3.

        The fetch must be stubbed: S3 (and moto) attach a native ChecksumCRC32 to
        every PutObject, so a genuinely checksum-free object cannot be created and
        auto-detection would otherwise legitimately choose crc32.
        """
        s3.put_object(Bucket=BUCKET, Key="file.txt", Body=b"data")
        monkeypatch.setattr(
            "catalog_client.utils.checksum.generate._fetch_all_s3_stored_checksums",
            lambda *a, **k: {},
        )

        assets = [make_asset(f"s3://{BUCKET}/file.txt")]
        result = checksums.for_assets(assets, algorithm=None, s3_client=s3)
        assert result[0].checksum is not None
        assert result[0].checksum_alg == "blake3"

    def test_auto_detect_folder_common_algorithm(self, s3):
        """algorithm=None on S3 folder where all children share blake3."""
        for name, digest in [("a.txt", "aa" * 32), ("b.txt", "bb" * 32)]:
            s3.put_object(
                Bucket=BUCKET,
                Key=f"dataset/{name}",
                Body=b"data",
                Metadata={"x-checksum-blake3": digest},
            )

        assets = [make_asset(f"s3://{BUCKET}/dataset/", asset_type=AssetType.folder)]
        result = checksums.for_assets(assets, algorithm=None, s3_client=s3)
        assert result[0].checksum is not None
        assert result[0].checksum_alg == "blake3"

    def test_auto_detect_folder_with_no_usable_checksums_falls_back_to_blake3(self, s3):
        """algorithm=None where no child carries a readable checksum -> blake3.

        No longer needs stubbing: SHA256 is a native checksum this library does
        not read, so it produces a genuinely unreadable folder through the real
        code path rather than a mocked one.
        """
        for name in ["a.txt", "b.txt"]:
            _put(s3, f"dataset/{name}")

        assets = [make_asset(f"s3://{BUCKET}/dataset/", asset_type=AssetType.folder)]
        result = checksums.for_assets(assets, algorithm=None, s3_client=s3)
        assert result[0].checksum is not None
        assert result[0].checksum_alg == "blake3"

    def test_auto_detect_folder_with_one_gap_downloads_only_that_child(self, s3):
        """A child without a stored checksum costs one download, not the folder.

        The download count is the assertion that matters: requiring an
        algorithm common to every child meant one gap re-fetched everything,
        and a digest-only assertion would not have noticed.
        """
        for name in ["a.txt", "c.txt", "d.txt"]:
            _put(s3, f"dataset/{name}", **{"x-checksum-blake3": hex64(name)})
        _put(s3, "dataset/b.txt")  # the only child that must be read

        assets = [make_asset(f"s3://{BUCKET}/dataset/", asset_type=AssetType.folder)]
        with patch.object(s3, "get_object", wraps=s3.get_object) as spy:
            result = checksums.for_assets(assets, algorithm=None, s3_client=s3)

        assert spy.call_count == 1
        assert spy.call_args.kwargs["Key"] == "dataset/b.txt"
        assert result[0].checksum_alg == "blake3"
        assert result[0].checksum is not None

    def test_auto_detect_folder_with_full_coverage_downloads_nothing(self, s3):
        for name in ["a.txt", "b.txt", "c.txt"]:
            _put(s3, f"dataset/{name}", **{"x-checksum-blake3": hex64(name)})

        assets = [make_asset(f"s3://{BUCKET}/dataset/", asset_type=AssetType.folder)]
        with patch.object(s3, "get_object", wraps=s3.get_object) as spy:
            checksums.for_assets(assets, algorithm=None, s3_client=s3)

        spy.assert_not_called()

    def test_access_error_warns(self, s3):
        """A real botocore NoSuchBucket error is caught and surfaced as a warning."""
        assets = [make_asset("s3://nonexistent-bucket/file.txt")]
        with pytest.warns(
            checksums.ChecksumWarning, match="Failed to generate checksum"
        ) as rec:
            result = checksums.for_assets(assets, algorithm="blake3", s3_client=s3)
        assert len(rec) == 1
        assert result[0].checksum is None

    def test_compute_if_no_s3_checksum_false_skips_s3(self, s3):
        """S3 file with no stored checksum + flag=False -> skipped."""
        s3.put_object(Bucket=BUCKET, Key="file.txt", Body=b"data")

        assets = [make_asset(f"s3://{BUCKET}/file.txt")]
        result = checksums.for_assets(
            assets, algorithm="blake3", compute_if_no_s3_checksum=False, s3_client=s3
        )
        assert result[0].checksum is None

    def test_compute_if_no_s3_checksum_false_does_not_skip_local(self, tmp_path):
        """Non-S3 asset is still computed even with flag=False."""
        target = tmp_path / "file.txt"
        target.write_text("data")

        assets = [make_asset(str(target), platform=StoragePlatform.sf_hpc)]
        result = checksums.for_assets(
            assets, algorithm="blake3", compute_if_no_s3_checksum=False
        )
        assert result[0].checksum is not None

    def test_mixed_platforms(self, s3, tmp_path):
        """S3, local, and unsupported assets processed correctly together."""
        s3.put_object(Bucket=BUCKET, Key="test.txt", Body=b"s3 content")
        local = tmp_path / "local.txt"
        local.write_text("local content")

        assets = [
            make_asset(f"s3://{BUCKET}/test.txt"),
            make_asset(str(local), platform=StoragePlatform.sf_hpc),
            make_asset("http://unsupported.com/file", platform=StoragePlatform.other),
        ]

        with pytest.warns(checksums.ChecksumWarning, match="not supported"):
            result = checksums.for_assets(assets, algorithm="blake3", s3_client=s3)

        assert result[0].checksum is not None  # S3
        assert result[1].checksum is not None  # local
        assert result[2].checksum is None  # unsupported
