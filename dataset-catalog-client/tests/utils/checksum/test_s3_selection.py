"""
Discovery and folder algorithm selection, from the listing alone.

Selection issues no HeadObject and no GetObject, so everything it decides is
decided from ListObjectsV2 fields — which is exactly what moto cannot vary
(see tests/utils/checksum/stub_s3.py). These tests therefore drive StubS3, and
a passing moto test elsewhere is not coverage of anything asserted here.
"""

import pytest

from catalog_client.utils.checksum.algorithm import Algorithm, default_algorithm
from catalog_client.utils.checksum.s3 import (
    _S3_NATIVE_NAME,
    _S3_NATIVE_RESPONSE_KEY,
    _iter_listing,
    _select_folder_algorithm,
)
from tests.utils.checksum.stub_s3 import StubObject, StubS3

BUCKET = "test-bucket"
PREFIX = "dataset/"
FOLDER = f"s3://{BUCKET}/{PREFIX}"

# Ranking is intersected with what this install can compute, so pin the set
# rather than letting the outcome depend on which optional extras are present.
BOTH_NATIVE = {
    Algorithm.blake3,
    Algorithm.blake2b,
    Algorithm.crc32,
    Algorithm.crc64nvme,
}


@pytest.fixture
def pin_available(monkeypatch):
    def pin(algorithms=BOTH_NATIVE):
        monkeypatch.setattr(
            "catalog_client.utils.checksum.s3.available_algorithms",
            lambda: set(algorithms),
        )

    return pin


def listed(key, **kwargs):
    return StubObject(key=f"{PREFIX}{key}", **kwargs)


def select(s3, algorithm=None):
    return _select_folder_algorithm(FOLDER, s3, algorithm)


# ── Discovery ─────────────────────────────────────────────────────────────────


def test_every_page_is_consumed_in_one_listing_pass():
    s3 = StubS3([listed(f"{i}.bin") for i in range(7)], page_size=2)

    objects = list(select(s3).objects)

    assert [o.key for o in objects] == [f"{PREFIX}{i}.bin" for i in range(7)]
    assert s3.list_calls == 1


def test_folder_marker_keys_are_excluded():
    s3 = StubS3([listed(""), listed("sub/"), listed("a.bin")])

    assert [o.key for o in select(s3).objects] == [f"{PREFIX}a.bin"]


def test_fields_the_listing_withholds_stay_none():
    s3 = StubS3([listed("a.bin", size=None, etag=None)])

    (obj,) = _iter_listing(s3, BUCKET, PREFIX)

    assert obj.size is None
    assert obj.algorithms is None
    assert obj.checksum_type is None
    assert obj.etag is None


def test_an_empty_algorithm_list_is_not_the_same_as_a_missing_one():
    # The distinction the whole hint model rests on: [] is evidence that the
    # object has no native checksum, absence is evidence of nothing.
    s3 = StubS3([listed("empty.bin", listing_algorithms=[]), listed("absent.bin")])

    empty, absent = _iter_listing(s3, BUCKET, PREFIX)

    assert empty.algorithms == frozenset()
    assert absent.algorithms is None


def test_a_missing_size_is_not_zero():
    s3 = StubS3([listed("a.bin", size=None)])

    assert next(iter(_iter_listing(s3, BUCKET, PREFIX))).size is None


# ── Selection issues no requests ──────────────────────────────────────────────


@pytest.mark.parametrize("algorithm", [None, Algorithm.crc32])
def test_selection_issues_no_head_or_get(algorithm):
    s3 = StubS3([listed("a.bin", body=b"x").with_native(Algorithm.crc32)])

    list(select(s3, algorithm).objects)

    assert s3.heads == []
    assert s3.gets == []


def test_an_explicit_algorithm_leaves_the_listing_unconsumed():
    # Nothing has to be ranked, so resolution may start on the first page
    # rather than waiting out pagination.
    s3 = StubS3([listed(f"{i}.bin") for i in range(6)], page_size=2)

    selection = select(s3, Algorithm.crc32)

    assert s3.pages_yielded == 0
    next(iter(selection.objects))
    assert s3.pages_yielded == 1


def test_auto_selection_drains_the_listing_before_choosing():
    # Ranking is over folder-wide totals, so it cannot start early. Asserted so
    # the barrier stays a deliberate choice rather than an accident.
    s3 = StubS3([listed(f"{i}.bin") for i in range(6)], page_size=2)

    select(s3)

    assert s3.pages_yielded == 3


# ── Selection ─────────────────────────────────────────────────────────────────


def test_an_explicit_algorithm_is_honoured_without_ranking():
    s3 = StubS3([listed("a.bin").with_native(Algorithm.crc32)])

    assert select(s3, Algorithm.crc64nvme).algorithm == Algorithm.crc64nvme


def test_ranking_follows_bytes_when_counts_are_equal(pin_available):
    # Each algorithm covers exactly one object, so only the size of what is
    # left decides: crc32 leaves one byte, crc64nvme leaves four megabytes.
    pin_available()
    s3 = StubS3(
        [
            listed("big.bin", size=4_000_000, listing_algorithms=["CRC32"]),
            listed("small.bin", size=1, listing_algorithms=["CRC64NVME"]),
        ]
    )

    assert select(s3).algorithm == Algorithm.crc32


def test_ranking_follows_object_count_when_bytes_are_equal(pin_available):
    # Both options leave 20,000 bytes to fetch; crc32 leaves them in one object
    # and crc64nvme in twenty. Round trips are the only difference, which is
    # the half of the cost model bytes alone would miss.
    pin_available()
    s3 = StubS3(
        [
            listed(f"many-{i:02d}.bin", size=1_000, listing_algorithms=["CRC32"])
            for i in range(20)
        ]
        + [listed("one.bin", size=20_000, listing_algorithms=["CRC64NVME"])]
    )

    assert select(s3).algorithm == Algorithm.crc32


def test_priority_breaks_ties_when_recompute_is_equal(pin_available):
    # Every object carries both, so neither needs a download and the cost model
    # cannot separate them. Only then does the priority table decide.
    pin_available()
    s3 = StubS3(
        [
            listed(n, size=10, listing_algorithms=["CRC32", "CRC64NVME"])
            for n in ("a.bin", "b.bin")
        ]
    )

    assert select(s3).algorithm == Algorithm.crc64nvme


def test_a_composite_only_algorithm_is_not_a_candidate(pin_available):
    # A composite value is not comparable with a whole-object hash, so an
    # algorithm only ever seen as COMPOSITE covers nothing.
    pin_available()
    s3 = StubS3(
        [
            listed(
                "a.bin",
                size=10,
                listing_algorithms=["CRC32"],
                listing_checksum_type="COMPOSITE",
            )
        ]
    )

    assert select(s3).algorithm == default_algorithm()


def test_an_algorithm_this_install_cannot_compute_is_never_selected(pin_available):
    # Combining children into a folder digest needs a working hasher, so an
    # algorithm S3 stored but that this install cannot build would fail
    # partway through the walk rather than at selection time.
    pin_available({Algorithm.blake3, Algorithm.blake2b, Algorithm.crc32})
    s3 = StubS3([listed("a.bin", size=10, listing_algorithms=["CRC64NVME"])])

    assert select(s3).algorithm == default_algorithm()


def test_no_native_candidate_falls_back_to_the_default():
    s3 = StubS3([listed("a.bin", size=10, listing_algorithms=[]), listed("b.bin")])

    assert select(s3).algorithm == default_algorithm()


def test_an_empty_prefix_falls_back_to_the_default():
    assert select(StubS3([])).algorithm == default_algorithm()


def test_an_empty_prefix_passes_an_explicit_algorithm_through():
    assert select(StubS3([]), Algorithm.crc32).algorithm == Algorithm.crc32


def test_a_local_path_selects_nothing():
    selection = _select_folder_algorithm("/local/path", None)

    assert selection.algorithm is None
    assert list(selection.objects) == []


# ── The multipart-ETag cost heuristic ─────────────────────────────────────────


@pytest.mark.parametrize("etag", ['"abc123"-4', "abc123-4"])
def test_a_multipart_etag_with_no_checksum_type_is_priced_as_a_download(
    pin_available, etag
):
    # S3 quotes the ETag in a listing, and the part-count suffix has to be the
    # last characters for the predicate to see it, so the quotes must come off.
    # Both shapes are covered because an S3-compatible store may not quote.
    #
    # crc32 covers the 4MB object on paper but its ETag says multipart with no
    # ChecksumType, which is what a composite looks like on a listing that
    # omits the type. crc64nvme's one-byte object is the cheaper bet.
    pin_available()
    s3 = StubS3(
        [
            listed("big.bin", size=4_000_000, listing_algorithms=["CRC32"], etag=etag),
            listed("small.bin", size=1, listing_algorithms=["CRC64NVME"]),
        ]
    )

    assert select(s3).algorithm == Algorithm.crc64nvme


def test_an_explicit_full_object_type_overrides_a_multipart_etag(pin_available):
    # A multipart upload may still carry a whole-object checksum. When S3 says
    # so outright, the ETag guess must not contradict it.
    pin_available()
    s3 = StubS3(
        [
            listed(
                "big.bin",
                size=4_000_000,
                listing_algorithms=["CRC32"],
                listing_checksum_type="FULL_OBJECT",
                etag='"abc123"-4',
            ),
            listed("small.bin", size=1, listing_algorithms=["CRC64NVME"]),
        ]
    )

    assert select(s3).algorithm == Algorithm.crc32


@pytest.mark.parametrize("etag", [None, '"abc123"'])
def test_an_absent_or_single_part_etag_keeps_the_reusable_estimate(pin_available, etag):
    pin_available()
    s3 = StubS3(
        [
            listed("big.bin", size=4_000_000, listing_algorithms=["CRC32"], etag=etag),
            listed("small.bin", size=1, listing_algorithms=["CRC64NVME"]),
        ]
    )

    assert select(s3).algorithm == Algorithm.crc32


def test_a_multipart_etag_alone_does_not_remove_a_candidate(pin_available):
    # Priced pessimistically, but still the only candidate there is — it must
    # not be struck out in favour of downloading everything under the default.
    pin_available()
    s3 = StubS3(
        [listed("a.bin", size=10, listing_algorithms=["CRC32"], etag='"abc123"-9')]
    )

    assert select(s3).algorithm == Algorithm.crc32


# ── The accepted tradeoff ─────────────────────────────────────────────────────


def test_metadata_only_algorithms_do_not_influence_automatic_selection():
    # A blake3 in user metadata is invisible to a listing, so automatic
    # selection cannot see it and picks the native algorithm instead. This is
    # the documented cost of not HEADing every object before choosing; naming
    # the algorithm explicitly still reuses the stored value.
    body = b"payload"
    obj = StubObject(key=f"{PREFIX}a.bin", body=body).with_native(Algorithm.crc32)
    obj.metadata = {"x-checksum-blake3": "aa" * 32}

    assert select(StubS3([obj])).algorithm == Algorithm.crc32
    assert select(StubS3([obj]), Algorithm.blake3).algorithm == Algorithm.blake3


# ── Canonical native naming ───────────────────────────────────────────────────


def test_native_names_match_listing_values_and_derive_the_head_keys():
    # One mapping feeds both shapes: ListObjectsV2 reports the bare name and
    # HeadObject returns "Checksum" + name. Two hand-written tables were free
    # to disagree; this asserts they cannot.
    assert _S3_NATIVE_NAME == {
        Algorithm.crc32: "CRC32",
        Algorithm.crc64nvme: "CRC64NVME",
    }
    assert _S3_NATIVE_RESPONSE_KEY == {
        Algorithm.crc32: "ChecksumCRC32",
        Algorithm.crc64nvme: "ChecksumCRC64NVME",
    }
