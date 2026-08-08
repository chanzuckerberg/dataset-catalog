"""The property that makes checksums useful: same content, same digest.

A digest must not depend on where the content lives, how it was reached, or
whether it was hashed on its own or as part of a folder. Everything here is a
regression guard for that single property — these tests fail loudly if any
code path reintroduces a second, incompatible notion of "the digest".

S3 cases run against moto so they exercise real HeadObject / ListObjectsV2
response shapes rather than a mock's idea of them.
"""

import boto3
import pytest
from moto import mock_aws

from catalog_client.models.asset import AssetType, DataAssetRequest, StoragePlatform
from catalog_client.utils.checksum import Algorithm, for_assets, for_location
from catalog_client.utils.checksum.hashing import (
    compute_checksum_localfs,
    compute_checksum_s3,
)

BUCKET = "repro-bucket"
BODY = b"the quick brown fox jumps over the lazy dog"

# blake2b is stdlib, so these tests hold on a base install too.
ALGORITHMS = [Algorithm.blake2b, Algorithm.crc32, Algorithm.blake3, Algorithm.crc64]


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def s3_asset(uri, asset_type):
    return DataAssetRequest(
        location_uri=uri, asset_type=asset_type, storage_platform=StoragePlatform.s3
    )


# ── A file's digest does not depend on being inside a folder ──────────────────


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_local_file_digest_same_standalone_and_as_folder_child(tmp_path, algorithm):
    (tmp_path / "inner.bin").write_bytes(BODY)

    standalone = compute_checksum_localfs(str(tmp_path / "inner.bin"), algorithm)
    as_child = compute_checksum_localfs(str(tmp_path), algorithm).children["inner.bin"]

    assert standalone.content_digest == as_child.content_digest


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_s3_file_digest_same_standalone_and_as_prefix_child(s3, algorithm):
    s3.put_object(Bucket=BUCKET, Key="ds/inner.bin", Body=BODY)

    standalone = compute_checksum_s3(
        f"s3://{BUCKET}/ds/inner.bin", algorithm, s3, use_stored=False
    )
    tree = compute_checksum_s3(f"s3://{BUCKET}/ds/", algorithm, s3, use_stored=False)

    assert standalone.content_digest == tree.children["inner.bin"].content_digest


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_nested_file_digest_survives_every_level_of_nesting(tmp_path, algorithm):
    """The same bytes at depth 0, 1 and 2 all produce one digest."""
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    (tmp_path / "f.bin").write_bytes(BODY)
    (tmp_path / "a" / "f.bin").write_bytes(BODY)
    (deep / "f.bin").write_bytes(BODY)

    root = compute_checksum_localfs(str(tmp_path), algorithm)
    depth0 = root.children["f.bin"].content_digest
    depth1 = root.children["a"].children["f.bin"].content_digest
    depth2 = root.children["a"].children["b"].children["f.bin"].content_digest

    assert depth0 == depth1 == depth2


# ── A digest does not depend on the path the content sits at ──────────────────


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_identical_content_at_different_paths_hashes_identically(tmp_path, algorithm):
    left = tmp_path / "left"
    right = tmp_path / "somewhere" / "deeper" / "right"
    left.mkdir()
    right.mkdir(parents=True)
    (left / "same-name.bin").write_bytes(BODY)
    (right / "same-name.bin").write_bytes(BODY)

    assert (
        compute_checksum_localfs(str(left), algorithm).content_digest
        == compute_checksum_localfs(str(right), algorithm).content_digest
    )


def test_local_and_s3_copies_of_the_same_bytes_agree(s3, tmp_path):
    """Storage backend is not part of the digest."""
    (tmp_path / "f.bin").write_bytes(BODY)
    s3.put_object(Bucket=BUCKET, Key="f.bin", Body=BODY)

    local = compute_checksum_localfs(str(tmp_path / "f.bin"), Algorithm.blake2b)
    remote = compute_checksum_s3(
        f"s3://{BUCKET}/f.bin", Algorithm.blake2b, s3, use_stored=False
    )

    assert local.content_digest == remote.content_digest


# ── A stored checksum is comparable with a computed one ───────────────────────


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_stored_metadata_child_and_downloaded_child_give_one_folder_root(s3, algorithm):
    """The bug this whole property guards against.

    Children read from S3 metadata and children downloaded and hashed must
    contribute identical bytes to the parent, or a folder appears to change
    the moment its objects gain metadata.
    """
    truth = {name: BODY + name.encode() for name in ("a.bin", "b.bin")}

    # Hash the objects for real first, then publish those digests as metadata
    # on a second copy — so the "stored" values are genuinely correct and the
    # test compares two routes to the same answer, not two arbitrary strings.
    for name, body in truth.items():
        s3.put_object(Bucket=BUCKET, Key=f"plain/{name}", Body=body)
    computed_children = {
        name: compute_checksum_s3(
            f"s3://{BUCKET}/plain/{name}", algorithm, s3, use_stored=False
        ).content_digest
        for name in truth
    }
    for name, body in truth.items():
        s3.put_object(
            Bucket=BUCKET,
            Key=f"meta/{name}",
            Body=body,
            Metadata={f"x-checksum-{algorithm}": computed_children[name]},
        )

    from_metadata = for_assets(
        [s3_asset(f"s3://{BUCKET}/meta/", AssetType.folder)],
        algorithm=algorithm,
        s3_client=s3,
    )[0].checksum
    from_download = compute_checksum_s3(
        f"s3://{BUCKET}/plain/", algorithm, s3, use_stored=False
    ).content_digest

    assert from_metadata == from_download


def test_native_crc32_matches_a_locally_computed_crc32(s3, tmp_path):
    """S3's own full-object CRC32 must equal what we compute over the bytes."""
    s3.put_object(Bucket=BUCKET, Key="f.bin", Body=BODY)
    (tmp_path / "f.bin").write_bytes(BODY)

    stored = compute_checksum_s3(
        f"s3://{BUCKET}/f.bin", Algorithm.crc32, s3, use_stored=True
    )
    computed = compute_checksum_localfs(str(tmp_path / "f.bin"), Algorithm.crc32)

    assert stored.source == "s3_native"
    assert stored.content_digest == computed.content_digest


# ── Folder digests react to content, not to how they were addressed ───────────


def test_folder_uri_with_and_without_trailing_slash_agree(s3):
    s3.put_object(Bucket=BUCKET, Key="ds/a.bin", Body=BODY)

    with_slash = for_assets(
        [s3_asset(f"s3://{BUCKET}/ds/", AssetType.folder)],
        algorithm=Algorithm.blake2b,
        s3_client=s3,
    )[0].checksum
    without_slash = for_assets(
        [s3_asset(f"s3://{BUCKET}/ds", AssetType.folder)],
        algorithm=Algorithm.blake2b,
        s3_client=s3,
    )[0].checksum

    assert with_slash is not None
    assert with_slash == without_slash


def test_sibling_prefix_sharing_a_name_stem_is_not_pulled_in(s3):
    """Listing "ds" must not sweep in "ds2/"."""
    s3.put_object(Bucket=BUCKET, Key="ds/a.bin", Body=BODY)
    only_ds = for_assets(
        [s3_asset(f"s3://{BUCKET}/ds", AssetType.folder)],
        algorithm=Algorithm.blake2b,
        s3_client=s3,
    )[0].checksum

    s3.put_object(Bucket=BUCKET, Key="ds2/intruder.bin", Body=b"different")
    still_only_ds = for_assets(
        [s3_asset(f"s3://{BUCKET}/ds", AssetType.folder)],
        algorithm=Algorithm.blake2b,
        s3_client=s3,
    )[0].checksum

    assert only_ds == still_only_ds


def test_for_location_and_for_assets_report_the_same_value(s3):
    """The two entry points must not disagree about a location's digest."""
    s3.put_object(Bucket=BUCKET, Key="f.bin", Body=BODY)

    via_location = for_location(
        f"s3://{BUCKET}/f.bin",
        AssetType.file,
        StoragePlatform.s3,
        Algorithm.blake2b,
        s3,
    ).value
    via_assets = for_assets(
        [s3_asset(f"s3://{BUCKET}/f.bin", AssetType.file)],
        algorithm=Algorithm.blake2b,
        s3_client=s3,
    )[0].checksum

    assert via_location == via_assets


def test_folder_digest_changes_when_a_child_changes(s3):
    """Reproducibility must not degenerate into insensitivity."""
    s3.put_object(Bucket=BUCKET, Key="ds/a.bin", Body=BODY)
    before = compute_checksum_s3(
        f"s3://{BUCKET}/ds/", Algorithm.blake2b, s3, use_stored=False
    ).content_digest

    s3.put_object(Bucket=BUCKET, Key="ds/a.bin", Body=BODY + b"!")
    after = compute_checksum_s3(
        f"s3://{BUCKET}/ds/", Algorithm.blake2b, s3, use_stored=False
    ).content_digest

    assert before != after


def test_folder_digest_changes_when_a_child_is_renamed(tmp_path):
    """Child names are part of a folder's identity, by design."""
    (tmp_path / "one.bin").write_bytes(BODY)
    before = compute_checksum_localfs(str(tmp_path), Algorithm.blake2b).content_digest

    (tmp_path / "one.bin").rename(tmp_path / "two.bin")
    after = compute_checksum_localfs(str(tmp_path), Algorithm.blake2b).content_digest

    assert before != after
