"""
Per-object resolution: which requests a worker issues, and what it reports.

The listing hint may only ever *cancel* a HeadObject that could not have
succeeded. It can never authorise reuse, because a listing carries no digest
values — so "the listing mentioned crc32" still costs a HEAD. Everything here
asserts request counts for that reason; a digest-only assertion would pass
against an implementation that trusted the hint.

Driven through StubS3: moto reports ChecksumAlgorithm on objects that have
none and never reports ChecksumType, so it cannot express a single row of the
table below. See tests/utils/checksum/stub_s3.py.
"""

import base64
import threading
import time

import pytest

from catalog_client.utils.checksum.algorithm import Algorithm, new_hasher
from catalog_client.utils.checksum.hashing import (
    _fold_s3_children,
    _resolve_s3_objects,
)
from tests.utils.checksum.stub_s3 import StubObject, StubS3, native_b64

BUCKET = "test-bucket"
PREFIX = "dataset/"

BODY = b"the object payload"


def listed(key, **kwargs):
    return StubObject(key=f"{PREFIX}{key}", body=kwargs.pop("body", BODY), **kwargs)


def resolve(
    s3, algorithm=Algorithm.crc32, *, download=True, use_stored=True, workers=1
):
    from catalog_client.utils.checksum.s3 import _iter_listing

    return _resolve_s3_objects(
        BUCKET,
        algorithm,
        s3,
        _iter_listing(s3, BUCKET, PREFIX),
        use_stored,
        None,
        download,
        hash_max_workers=None,
        s3_workers=workers,
    )


def metadata_hex(body: bytes, algorithm: Algorithm) -> str:
    hasher = new_hasher(algorithm)
    hasher.update(body)
    return hasher.hexdigest()


def computed_hex(body: bytes, algorithm: Algorithm) -> str:
    return metadata_hex(body, algorithm)


# ── The worker decision table ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "algorithms, why",
    [
        (["CRC64NVME"], "a different native algorithm"),
        ([], "an explicitly empty algorithm list"),
    ],
)
def test_a_listing_that_excludes_the_algorithm_skips_the_head(algorithms, why):
    s3 = StubS3([listed("a.bin", listing_algorithms=algorithms)])

    result = resolve(s3)

    assert s3.heads == [], why
    assert s3.gets == [f"{PREFIX}a.bin"]
    assert result.children[f"{PREFIX}a.bin"].source == "computed"


def test_a_composite_checksum_in_the_listing_skips_the_head():
    # A composite covers part checksums, not object bytes, so a HEAD could
    # only return a value that has to be thrown away.
    s3 = StubS3(
        [
            listed(
                "a.bin",
                listing_algorithms=["CRC32"],
                listing_checksum_type="COMPOSITE",
            )
        ]
    )

    resolve(s3)

    assert s3.heads == []
    assert s3.gets == [f"{PREFIX}a.bin"]


@pytest.mark.parametrize("checksum_type", ["FULL_OBJECT", None])
def test_a_reported_algorithm_is_headed_and_its_digest_reused(checksum_type):
    obj = listed("a.bin").with_native(Algorithm.crc32)
    if checksum_type is None:
        obj.listing_checksum_type = None
    s3 = StubS3([obj])

    result = resolve(s3)

    assert s3.heads == [f"{PREFIX}a.bin"]
    assert s3.gets == []
    child = result.children[f"{PREFIX}a.bin"]
    assert child.source == "s3_native"
    assert child.file_hash == computed_hex(BODY, Algorithm.crc32)


def test_a_listing_without_checksum_algorithms_still_heads():
    # The conservative fallback: an absent field is evidence of nothing, and
    # S3-compatible stores need not populate it.
    s3 = StubS3([listed("a.bin").with_native(Algorithm.crc32)])
    s3.objects[0].listing_algorithms = None
    s3.objects[0].listing_checksum_type = None

    resolve(s3)

    assert s3.heads == [f"{PREFIX}a.bin"]
    assert s3.gets == []


def test_a_metadata_backed_algorithm_always_heads():
    # The listing can never mention x-checksum-blake3, so a hint that omits
    # blake3 must not be read as ruling it out.
    obj = listed("a.bin", listing_algorithms=["CRC32"])
    obj.metadata = {"x-checksum-blake3": metadata_hex(BODY, Algorithm.blake3)}
    s3 = StubS3([obj])

    result = resolve(s3, Algorithm.blake3)

    assert s3.heads == [f"{PREFIX}a.bin"]
    assert s3.gets == []
    assert result.children[f"{PREFIX}a.bin"].source == "s3_metadata"


def test_a_multipart_etag_with_no_checksum_type_still_heads_and_reuses():
    # Priced as a download by the cost model, but the worker must not act on
    # that guess: a multipart object can carry a whole-object CRC64NVME.
    obj = listed("a.bin").with_native(Algorithm.crc64nvme)
    obj.listing_checksum_type = None
    obj.head.pop("ChecksumType")
    obj.etag = '"abc123"-7'
    s3 = StubS3([obj])

    result = resolve(s3, Algorithm.crc64nvme)

    assert s3.heads == [f"{PREFIX}a.bin"]
    assert s3.gets == []
    assert result.children[f"{PREFIX}a.bin"].source == "s3_native"


@pytest.mark.parametrize(
    "head, why",
    [
        ({}, "HEAD returned no checksum at all"),
        ({"ChecksumCRC32": "not-base64!!"}, "HEAD returned an undecodable value"),
        (
            {"ChecksumCRC32": base64.b64encode(b"\x01\x02").decode()},
            "HEAD returned a digest of the wrong width",
        ),
        (
            {"ChecksumCRC32": "abcd-9", "ChecksumType": "COMPOSITE"},
            "HEAD returned a composite checksum",
        ),
    ],
)
def test_an_unusable_head_digest_downloads_once_without_a_second_head(head, why):
    obj = listed("a.bin", listing_algorithms=["CRC32"])
    obj.head = head
    s3 = StubS3([obj])

    result = resolve(s3)

    assert s3.heads == [f"{PREFIX}a.bin"], why
    assert s3.gets == [f"{PREFIX}a.bin"], why
    assert result.children[f"{PREFIX}a.bin"].source == "computed"


def test_use_stored_false_bypasses_the_head_entirely():
    s3 = StubS3([listed("a.bin").with_native(Algorithm.crc32)])

    result = resolve(s3, use_stored=False)

    assert s3.heads == []
    assert s3.gets == [f"{PREFIX}a.bin"]
    assert result.children[f"{PREFIX}a.bin"].source == "computed"


# ── Coverage when downloading is disabled ─────────────────────────────────────


def test_downloads_disabled_makes_no_get_requests():
    s3 = StubS3([listed("a.bin"), listed("b.bin").with_native(Algorithm.crc32)])

    result = resolve(s3, download=False)

    assert s3.gets == []
    assert not result.complete
    assert list(result.children) == [f"{PREFIX}b.bin"]


def test_complete_stored_coverage_succeeds_with_downloads_disabled():
    s3 = StubS3(
        [
            listed("a.bin").with_native(Algorithm.crc32),
            listed("b.bin", body=b"other").with_native(Algorithm.crc32),
        ]
    )

    result = resolve(s3, download=False)

    assert s3.gets == []
    assert result.complete
    assert set(result.stored) == {
        f"s3://{BUCKET}/{PREFIX}a.bin",
        f"s3://{BUCKET}/{PREFIX}b.bin",
    }


def test_an_empty_prefix_is_not_complete_coverage():
    # Preserves the existing rule that a prefix with nothing in it does not
    # earn a digest under compute_if_no_s3_checksum=False.
    assert not resolve(StubS3([]), download=False).complete


def test_only_stored_digests_are_offered_for_caching():
    # A freshly computed digest was never validated against anything S3 holds,
    # so it must not enter a checksum cache.
    s3 = StubS3([listed("a.bin"), listed("b.bin").with_native(Algorithm.crc32)])

    result = resolve(s3)

    assert set(result.stored) == {f"s3://{BUCKET}/{PREFIX}b.bin"}
    assert set(result.children) == {f"{PREFIX}a.bin", f"{PREFIX}b.bin"}


def test_a_failing_object_raises_in_listing_order(monkeypatch):
    # Concurrency must not make which error surfaces depend on thread timing:
    # b.bin fails slowly and c.bin fails instantly, and b.bin is what a serial
    # pass would have hit first.
    s3 = StubS3([listed(n, listing_algorithms=[]) for n in ("a.bin", "b.bin", "c.bin")])
    real_get = s3.get_object

    def failing(Bucket, Key, **kwargs):  # noqa: N803 — botocore's shape
        if Key.endswith("b.bin"):
            time.sleep(0.05)
            raise RuntimeError("b.bin is unreadable")
        if Key.endswith("c.bin"):
            raise RuntimeError("c.bin is unreadable")
        return real_get(Bucket=Bucket, Key=Key, **kwargs)

    monkeypatch.setattr(s3, "get_object", failing)

    with pytest.raises(RuntimeError, match="b.bin is unreadable"):
        resolve(s3, workers=4)


# ── Concurrency ───────────────────────────────────────────────────────────────


def test_a_download_starts_while_another_objects_head_is_outstanding():
    # The removed barrier. a.bin's HEAD blocks on an event; b.bin's GET must be
    # observed *before* that event is released. Under the previous phase
    # ordering — every HEAD, then every GET — b.bin's GET cannot be issued
    # while a.bin's HEAD is outstanding, so this fails deterministically
    # rather than flaking. The polling below is only how the condition is
    # observed; the assertion is the condition, not any duration.
    slow = listed("a.bin").with_native(Algorithm.crc32)
    fast = listed("b.bin", body=b"other", listing_algorithms=[])
    s3 = StubS3([slow, fast])
    gate = threading.Event()
    s3.head_gate[f"{PREFIX}a.bin"] = gate

    resolver = threading.Thread(target=lambda: resolve(s3, workers=4), daemon=True)
    resolver.start()
    try:
        deadline = time.monotonic() + 5
        while f"{PREFIX}b.bin" not in s3.gets and time.monotonic() < deadline:
            time.sleep(0.005)
        assert f"{PREFIX}b.bin" in s3.gets, (
            "b.bin's GET never started while a.bin's HEAD was outstanding"
        )
    finally:
        gate.set()
        resolver.join(timeout=10)
    assert not resolver.is_alive()


@pytest.mark.parametrize("workers", [1, 2, 8, 32])
def test_the_folder_digest_does_not_depend_on_worker_count(workers):
    objects = [listed(f"{i}.bin", body=bytes([i]) * (i + 1)) for i in range(8)]
    objects[3].with_native(Algorithm.crc32)
    objects[6].with_native(Algorithm.crc32)

    result = resolve(StubS3(objects), workers=workers)
    folded = _fold_s3_children(BUCKET, PREFIX, result.children, Algorithm.crc32)

    assert folded.file_hash == _EXPECTED_FOLDER_DIGEST


def _folder_digest_once():
    objects = [listed(f"{i}.bin", body=bytes([i]) * (i + 1)) for i in range(8)]
    objects[3].with_native(Algorithm.crc32)
    objects[6].with_native(Algorithm.crc32)
    result = resolve(StubS3(objects), workers=1)
    return _fold_s3_children(BUCKET, PREFIX, result.children, Algorithm.crc32).file_hash


_EXPECTED_FOLDER_DIGEST = _folder_digest_once()


def test_the_explicit_and_automatic_routes_agree_on_the_digest():
    from catalog_client.utils.checksum.s3 import _select_folder_algorithm

    def run(algorithm):
        objects = [listed(f"{i}.bin", body=bytes([i]) * (i + 1)) for i in range(4)]
        for obj in objects:
            obj.with_native(Algorithm.crc32)
        s3 = StubS3(objects, page_size=2)
        selection = _select_folder_algorithm(f"s3://{BUCKET}/{PREFIX}", s3, algorithm)
        resolution = _resolve_s3_objects(
            BUCKET,
            selection.algorithm,
            s3,
            selection.objects,
            True,
            None,
            True,
            4,
        )
        return _fold_s3_children(
            BUCKET, PREFIX, resolution.children, selection.algorithm
        ).file_hash

    assert run(Algorithm.crc32) == run(None)


# ── Sizes ─────────────────────────────────────────────────────────────────────


def test_a_size_neither_listing_nor_head_reported_stays_none():
    # None, not 0: an unknown size must not read as an empty object.
    obj = listed("a.bin").with_native(Algorithm.crc32)
    obj.size = None
    obj.head["ContentLength"] = None

    result = resolve(StubS3([obj]))

    assert result.children[f"{PREFIX}a.bin"].total_size is None


def test_the_listing_size_backfills_a_stored_result_that_lacks_one():
    obj = listed("a.bin").with_native(Algorithm.crc32)
    obj.head["ContentLength"] = None
    obj.size = 4242

    result = resolve(StubS3([obj]))

    assert result.children[f"{PREFIX}a.bin"].total_size == 4242


def test_native_b64_matches_the_hashers_own_digest():
    assert base64.b64decode(native_b64(BODY, Algorithm.crc32)).hex() == metadata_hex(
        BODY, Algorithm.crc32
    )
