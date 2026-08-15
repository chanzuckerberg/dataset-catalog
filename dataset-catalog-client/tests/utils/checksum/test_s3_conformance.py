"""Do our S3-native digests equal the ones S3 itself computed?

The other checksum tests compare our code against our code. These compare it
against an oracle: objects are uploaded with `ChecksumAlgorithm=...` so S3 —
not this library — computes the checksum, and we assert byte-for-byte equality
with what we produce locally, in S3's own base64 encoding.

moto is a real oracle for this, not a stub: it computes actual CRCs (its
CRC64NVME of b"123456789" is the published NVMe check value 0xae8b14860a799888)
and it computes real multipart composites. Two fidelity gaps to know about:

  - moto does not return ChecksumType, so these tests exercise the suffix
    fallback in _is_composite rather than the explicit-field branch. The field
    branch is covered with mocks in test_s3_stored.py.
  - moto stores a multipart composite with no "-N" suffix, which real S3 always
    adds. So a composite object here looks full-object to our detection code.
    That is moto being wrong, not us, which is why the composite test below
    compares digests directly instead of going through _fetch_s3_stored_checksum.

Everything here is parametrized off _S3_NATIVE_RESPONSE_KEY, so adding an
algorithm to that dict enrols it in the conformance suite automatically.
"""

import boto3
import pytest
from moto import mock_aws

from catalog_client.utils.checksum import hashing
from catalog_client.utils.checksum.algorithm import Algorithm
from catalog_client.utils.checksum.hashing import (
    compute_checksum_localfs,
    compute_checksum_s3,
)
from catalog_client.utils.checksum.s3 import (
    _NON_S3_NATIVE_ALGORITHMS,
    _S3_NATIVE_RESPONSE_KEY,
)

BUCKET = "conformance-bucket"

# Boundaries around the 64KB READ_BUFFER, plus a size spanning many buffers.
SIZES = [0, 1, 64 * 1024 - 1, 64 * 1024, 64 * 1024 + 1, 1024 * 1024 + 7]

NATIVE = sorted(_S3_NATIVE_RESPONSE_KEY.items())
native_algorithms = pytest.mark.parametrize(
    "algorithm, response_key", NATIVE, ids=[a.value for a, _ in NATIVE]
)

_PATTERN = bytes(range(251))


def payload(size: int) -> bytes:
    return (_PATTERN * (size // len(_PATTERN) + 1))[:size]


def s3_algorithm_name(algorithm: Algorithm) -> str:
    """The name S3's ChecksumAlgorithm parameter uses for one of our algorithms."""
    return algorithm.value.upper()


def strip_part_count(value: str) -> str:
    """Drop the "-N" part count real S3 appends to a composite checksum."""
    head, dash, tail = value.rpartition("-")
    return head if dash and tail.isdigit() else value


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture
def local(tmp_path):
    def write(body, name="f.bin"):
        path = tmp_path / name
        path.write_bytes(body)
        return str(path)

    return write


# ── Whole-object native checksums ─────────────────────────────────────────────


@native_algorithms
@pytest.mark.parametrize("size", SIZES, ids=[str(s) for s in SIZES])
def test_our_digest_equals_the_one_s3_computed(
    s3, local, algorithm, response_key, size
):
    """The core of claim 3: our value is S3's value, in S3's encoding."""
    body = payload(size)
    s3.put_object(
        Bucket=BUCKET,
        Key="o",
        Body=body,
        ChecksumAlgorithm=s3_algorithm_name(algorithm),
    )
    from_s3 = s3.head_object(Bucket=BUCKET, Key="o", ChecksumMode="ENABLED")

    ours = compute_checksum_localfs(local(body), algorithm)

    assert ours.s3_base64 == from_s3[response_key]


@native_algorithms
def test_a_stored_native_checksum_is_read_back_as_the_same_digest(
    s3, local, algorithm, response_key
):
    """Reading S3's checksum and computing our own must agree.

    This is the join between claim 3 and claim 1: if they disagreed, a folder's
    digest would depend on whether its children happened to carry a stored
    checksum.
    """
    body = payload(4096)
    s3.put_object(
        Bucket=BUCKET,
        Key="o",
        Body=body,
        ChecksumAlgorithm=s3_algorithm_name(algorithm),
    )

    stored = compute_checksum_s3(f"s3://{BUCKET}/o", algorithm, s3, use_stored=True)
    computed = compute_checksum_localfs(local(body), algorithm)

    assert stored.source == "s3_native"
    assert stored.content_digest == computed.content_digest


@native_algorithms
def test_every_child_of_a_prefix_matches_s3s_own_value(
    s3, local, algorithm, response_key
):
    """Claim 2 measured against the oracle rather than against ourselves."""
    bodies = {"a.bin": payload(10), "sub/b.bin": payload(70_000)}
    for key, body in bodies.items():
        s3.put_object(
            Bucket=BUCKET,
            Key=f"ds/{key}",
            Body=body,
            ChecksumAlgorithm=s3_algorithm_name(algorithm),
        )

    tree = compute_checksum_s3(f"s3://{BUCKET}/ds/", algorithm, s3, use_stored=True)

    def s3_value(key):
        head = s3.head_object(Bucket=BUCKET, Key=f"ds/{key}", ChecksumMode="ENABLED")
        return head[response_key]

    def child_of(tree, key):
        node = tree
        for part in key.split("/"):
            node = node.children[part]
        return node

    for key, body in bodies.items():
        child = child_of(tree, key)
        # S3's own value for this object, at whatever depth it sits.
        assert child.s3_base64 == s3_value(key)
        # ...and the same value a purely local hash of those bytes produces.
        local_copy = compute_checksum_localfs(
            local(body, name=key.replace("/", "_")), algorithm
        )
        assert child.content_digest == local_copy.content_digest


@native_algorithms
@pytest.mark.parametrize("workers", [1, 2, 3, 8], ids=lambda w: f"w{w}")
def test_a_prefix_digest_is_the_same_at_any_worker_count(
    s3, algorithm, response_key, workers
):
    """Fetching children concurrently must not move a single digest byte.

    Worker counts 2 and 3 divide 7 children unevenly on purpose, so the
    completion order genuinely differs between runs. What the digest depends on
    is the order children are *combined* in, which stays sorted regardless.
    """
    keys = ["a.bin", "b.bin", "sub/c.bin", "sub/d.bin", "sub/deep/e.bin", "f.bin", "g"]
    for index, key in enumerate(keys):
        s3.put_object(
            Bucket=BUCKET,
            Key=f"ds/{key}",
            Body=payload(index * 3_000),
            ChecksumAlgorithm=s3_algorithm_name(algorithm),
        )

    serial = compute_checksum_s3(
        f"s3://{BUCKET}/ds/", algorithm, s3, use_stored=False, max_workers=1
    )
    parallel = compute_checksum_s3(
        f"s3://{BUCKET}/ds/", algorithm, s3, use_stored=False, max_workers=workers
    )

    def digest_map(node, prefix=""):
        flat = {prefix or ".": node.content_digest}
        for name, child in node.children.items():
            flat.update(digest_map(child, f"{prefix}{name}/"))
        return flat

    assert parallel.content_digest == serial.content_digest
    assert parallel.total_size == serial.total_size
    # Per-path, so a failure names the child rather than only the root, and so
    # two children swapping digests cannot pass on a root comparison alone.
    assert digest_map(parallel) == digest_map(serial)


# ── The native/non-native split is real, not just a comment ──────────────────


@pytest.mark.parametrize(
    "algorithm", sorted(_NON_S3_NATIVE_ALGORITHMS), ids=lambda a: a.value
)
def test_s3_rejects_the_algorithms_we_classify_as_non_native(s3, algorithm):
    """Closes the split in the other direction.

    _NON_S3_NATIVE_ALGORITHMS is derived by subtraction, so without this the
    claim "S3 cannot compute these" rests on nothing. If S3 ever gains one of
    them natively, this test fails and _S3_NATIVE_RESPONSE_KEY needs the entry.
    """
    with pytest.raises(Exception, match="(?i)unsupported checksum algorithm"):
        s3.put_object(
            Bucket=BUCKET,
            Key="o",
            Body=b"x",
            ChecksumAlgorithm=s3_algorithm_name(algorithm),
        )


@native_algorithms
def test_s3_accepts_every_algorithm_we_classify_as_native(s3, algorithm, response_key):
    s3.put_object(
        Bucket=BUCKET,
        Key="o",
        Body=b"x",
        ChecksumAlgorithm=s3_algorithm_name(algorithm),
    )
    head = s3.head_object(Bucket=BUCKET, Key="o", ChecksumMode="ENABLED")
    assert response_key in head


# ── Multipart composite ───────────────────────────────────────────────────────

PART_SIZE = 5 * 1024 * 1024  # S3's minimum for a non-final part


@pytest.fixture
def multipart(s3):
    """Upload `bodies` as ordered parts and return the completed object's head."""

    def upload(key, bodies, algorithm):
        started = s3.create_multipart_upload(
            Bucket=BUCKET, Key=key, ChecksumAlgorithm=s3_algorithm_name(algorithm)
        )
        parts = []
        for number, body in enumerate(bodies, start=1):
            part = s3.upload_part(
                Bucket=BUCKET,
                Key=key,
                UploadId=started["UploadId"],
                PartNumber=number,
                Body=body,
            )
            parts.append({"ETag": part["ETag"], "PartNumber": number})
        s3.complete_multipart_upload(
            Bucket=BUCKET,
            Key=key,
            UploadId=started["UploadId"],
            MultipartUpload={"Parts": parts},
        )
        return s3.head_object(Bucket=BUCKET, Key=key, ChecksumMode="ENABLED")

    return upload


def test_our_composite_equals_s3s_multipart_checksum(multipart, local, monkeypatch):
    """merkle_root is claimed to be "the S3-style CRC of concatenated chunk
    CRCs". This is the only test that checks that against S3 rather than
    against the same formula written twice.

    CHUNK_SIZE is set to the uploader's part size, because a composite is only
    reproducible when the partitioning matches — which is exactly why a
    composite is never accepted as a whole-object digest (test_s3_stored.py).
    """
    bodies = [payload(PART_SIZE), payload(1000)]
    head = multipart("mp", bodies, Algorithm.crc32)

    monkeypatch.setattr(hashing, "CHUNK_SIZE", PART_SIZE)
    ours = compute_checksum_localfs(local(b"".join(bodies)), Algorithm.crc32)

    assert len(ours.chunks) == len(bodies)
    assert ours.s3_composite_base64 == strip_part_count(head["ChecksumCRC32"])


def test_a_composite_is_not_the_whole_object_digest(multipart, local, monkeypatch):
    """The discrimination pair for the test above.

    If these two were ever equal the distinction between merkle_root and
    file_hash would be untested, and storing the wrong one would be invisible.
    """
    bodies = [payload(PART_SIZE), payload(1000)]
    multipart("mp", bodies, Algorithm.crc32)

    monkeypatch.setattr(hashing, "CHUNK_SIZE", PART_SIZE)
    ours = compute_checksum_localfs(local(b"".join(bodies)), Algorithm.crc32)

    assert ours.s3_composite_base64 != ours.s3_base64


def test_a_single_part_upload_composite_still_differs_from_the_full_object(
    multipart, local, monkeypatch
):
    """Even at one part, a composite is a CRC *of a CRC*, not the object's CRC.

    Real S3 marks this one "-1", which _has_multipart_suffix catches; the point
    here is that the underlying values genuinely differ, so treating a "-1"
    composite as a whole-object digest would be wrong rather than merely
    untidy.
    """
    body = payload(1000)
    multipart("mp", [body], Algorithm.crc32)

    monkeypatch.setattr(hashing, "CHUNK_SIZE", PART_SIZE)
    ours = compute_checksum_localfs(local(body), Algorithm.crc32)

    assert len(ours.chunks) == 1
    assert ours.s3_composite_base64 != ours.s3_base64
