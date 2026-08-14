"""
Do we agree with AWS itself, rather than with moto?

The unit suite's S3 conformance tests use moto, and its own docstring lists the
two places moto is not S3: it omits `ChecksumType`, and it stores a multipart
composite without the `-N` part-count suffix. Those are precisely the inputs
`_is_composite` exists to handle, so the branch that protects the catalog from
recording a part-size-dependent checksum as a whole-object digest is tested only
against mocks.

This dimension closes that with the real service. It is opt-in and never implied
by another tier, because it needs credentials and it writes objects.

Safety properties, since this is the one dimension with outside effects:
  - every key is created under <prefix>/<random run id>/, so it cannot collide
    with anything or with a concurrent run
  - only keys this run created are deleted, and they are listed in the report
  - --keep-s3-objects leaves them in place for inspection

    CATALOG_EVAL_S3_BUCKET=my-bucket python -m evals.checksum --tier aws
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterator
from pathlib import Path

from catalog_client.models.asset import AssetType, StoragePlatform
from catalog_client.utils.checksum.algorithm import Algorithm
from catalog_client.utils.checksum.generate import for_location
from catalog_client.utils.checksum.hashing import (
    compute_checksum_localfs,
    compute_checksum_s3,
)
from catalog_client.utils.checksum.s3 import (
    _NON_S3_NATIVE_ALGORITHMS,
    _S3_NATIVE_RESPONSE_KEY,
    _fetch_all_s3_stored_checksums,
)
from evals.checksum import corpus, oracles
from evals.checksum.harness import (
    Check,
    Context,
    Status,
    Tier,
    assert_that,
    chunking,
    compare,
    skip,
)

NAME = "aws_native"

SIZES = (0, 1, 64 * 1024 - 1, 64 * 1024, 64 * 1024 + 1, 1024 * 1024 + 7)
PART_SIZE = 5 * 1024 * 1024  # S3's minimum for a non-final part
MULTIPART_PARTS = (PART_SIZE, PART_SIZE, 1024 * 1024)


def _strip_part_count(value: str) -> str:
    head, dash, tail = value.rpartition("-")
    return head if dash and tail.isdigit() else value


def run(ctx: Context) -> Iterator[Check]:
    from evals.checksum.harness import available_algorithms

    if not ctx.wants(Tier.aws):
        yield skip(f"{NAME}.all", NAME, Tier.aws, "real-S3 checks need --tier aws")
        return
    if not ctx.s3_bucket:
        yield skip(
            f"{NAME}.all",
            NAME,
            Tier.aws,
            "no bucket: set CATALOG_EVAL_S3_BUCKET or pass --s3-bucket",
        )
        return

    import boto3

    s3 = boto3.client("s3")
    bucket = ctx.s3_bucket
    run_id = os.urandom(6).hex()
    prefix = f"{ctx.s3_prefix.strip('/')}/{run_id}"
    created: list[str] = []
    workdir = ctx.scratch("aws")
    algorithms = available_algorithms()

    def put(key: str, body: bytes, **kwargs) -> None:
        s3.put_object(Bucket=bucket, Key=key, Body=body, **kwargs)
        created.append(key)

    yield Check(
        id=f"{NAME}.target",
        dimension=NAME,
        tier=Tier.aws,
        status=Status.skipped,
        message=f"writing under s3://{bucket}/{prefix}/",
    )

    try:
        yield from _whole_object(ctx, s3, bucket, prefix, workdir, put)
        yield from _stored_readback(ctx, s3, bucket, prefix, workdir, put, algorithms)
        yield from _multipart_composite(ctx, s3, bucket, prefix, workdir, created)
        yield from _rejected_algorithms(ctx, s3, bucket, prefix)
        yield from _folder(ctx, s3, bucket, prefix, workdir, put)
    finally:
        if created and not ctx.keep_s3_objects:
            # Only the keys this run created, one page at a time.
            for start in range(0, len(created), 1000):
                s3.delete_objects(
                    Bucket=bucket,
                    Delete={
                        "Objects": [
                            {"Key": key} for key in created[start : start + 1000]
                        ]
                    },
                )
        yield Check(
            id=f"{NAME}.cleanup",
            dimension=NAME,
            tier=Tier.aws,
            status=Status.skipped,
            message=(
                f"left {len(created)} objects in place under {prefix}/"
                if ctx.keep_s3_objects
                else f"deleted {len(created)} objects created under {prefix}/"
            ),
            metrics={"objects": len(created)},
        )


def _whole_object(ctx, s3, bucket, prefix, workdir: Path, put) -> Iterator[Check]:
    """Our digest, in S3's encoding, against the value S3 computed for itself."""
    for algorithm, response_key in sorted(_S3_NATIVE_RESPONSE_KEY.items()):
        for size in SIZES:
            body = corpus.content(f"aws/{algorithm.value}/{size}", size)
            key = f"{prefix}/native/{algorithm.value}/{size}"
            put(key, body, ChecksumAlgorithm=algorithm.value.upper())
            head = s3.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")

            local = workdir / "body.bin"
            local.write_bytes(body)
            ours = compute_checksum_localfs(str(local), algorithm)
            case = f"{NAME}.{algorithm.value}.size{size}"

            yield compare(
                f"{case}.equals_aws",
                NAME,
                Tier.aws,
                ours.s3_base64,
                head.get(response_key),
                note="our digest must be byte-for-byte what AWS computed",
                size_bytes=size,
            )
            # The field moto never returns. A single-part upload is FULL_OBJECT,
            # which is what makes the stored value comparable to a whole-object
            # hash at all.
            yield compare(
                f"{case}.checksum_type",
                NAME,
                Tier.aws,
                head.get("ChecksumType"),
                "FULL_OBJECT",
                note="single-part uploads must report FULL_OBJECT, not COMPOSITE",
            )
            yield compare(
                f"{case}.content_length",
                NAME,
                Tier.aws,
                head.get("ContentLength"),
                size,
                note="the size we report comes from this field",
            )


def _stored_readback(
    ctx, s3, bucket, prefix, workdir: Path, put, algorithms
) -> Iterator[Check]:
    """Reading a stored checksum back must reproduce the digest, and the size."""
    size = 512 * 1024 + 3
    body = corpus.content("aws/readback", size)

    for algorithm in sorted(_S3_NATIVE_RESPONSE_KEY):
        key = f"{prefix}/readback/{algorithm.value}"
        put(key, body, ChecksumAlgorithm=algorithm.value.upper())
        result = compute_checksum_s3(
            f"s3://{bucket}/{key}", algorithm, s3_client=s3, use_stored=True
        )
        local = workdir / "readback.bin"
        local.write_bytes(body)
        case = f"{NAME}.readback.{algorithm.value}"

        yield compare(
            f"{case}.digest",
            NAME,
            Tier.aws,
            result.content_digest,
            oracles.digest(local, algorithm),
            note="a checksum read from S3 must equal one computed from the bytes",
        )
        yield compare(f"{case}.source", NAME, Tier.aws, result.source, "s3_native")
        yield compare(
            f"{case}.size_without_download",
            NAME,
            Tier.aws,
            result.total_size,
            size,
            note="HeadObject must supply the size on the no-download path",
        )
        # Recomputing must land on the same value as reading it, or the two
        # paths are not interchangeable.
        recomputed = compute_checksum_s3(
            f"s3://{bucket}/{key}", algorithm, s3_client=s3, use_stored=False
        )
        yield compare(
            f"{case}.recompute_agrees",
            NAME,
            Tier.aws,
            recomputed.content_digest,
            result.content_digest,
            note="downloading and hashing must match the stored value",
        )

    # The user-metadata path, for an algorithm S3 cannot compute itself.
    metadata_algorithm = next(
        (a for a in sorted(_NON_S3_NATIVE_ALGORITHMS) if a in algorithms), None
    )
    if metadata_algorithm is None:
        yield skip(
            f"{NAME}.readback.metadata",
            NAME,
            Tier.aws,
            "no non-native algorithm available in this install",
        )
        return

    local = workdir / "metadata.bin"
    local.write_bytes(body)
    expected = oracles.digest(local, metadata_algorithm)
    key = f"{prefix}/readback/metadata_{metadata_algorithm.value}"
    put(key, body, Metadata={f"x-checksum-{metadata_algorithm.value}": expected})

    result = compute_checksum_s3(
        f"s3://{bucket}/{key}", metadata_algorithm, s3_client=s3, use_stored=True
    )
    case = f"{NAME}.readback.metadata.{metadata_algorithm.value}"
    yield compare(f"{case}.digest", NAME, Tier.aws, result.content_digest, expected)
    yield compare(f"{case}.source", NAME, Tier.aws, result.source, "s3_metadata")
    yield compare(f"{case}.size", NAME, Tier.aws, result.total_size, size)


def _multipart_composite(
    ctx, s3, bucket, prefix, workdir: Path, created: list[str]
) -> Iterator[Check]:
    """
    The branch moto cannot reach: a real COMPOSITE checksum with a -N suffix.

    Two separate things are asserted, and they pull in opposite directions on
    purpose. Our composite must equal S3's composite when we partition the file
    the way the uploader did — that is what s3_composite_base64 is for. And that
    same value must be refused by the stored-checksum reader, because a caller
    who did not upload the object has no idea what part size produced it.
    """
    total = sum(MULTIPART_PARTS)
    body = corpus.content("aws/multipart", total)
    key = f"{prefix}/multipart/object"

    for algorithm, response_key in sorted(_S3_NATIVE_RESPONSE_KEY.items()):
        part_key = f"{key}.{algorithm.value}"
        upload = s3.create_multipart_upload(
            Bucket=bucket,
            Key=part_key,
            ChecksumAlgorithm=algorithm.value.upper(),
            ChecksumType="COMPOSITE",
        )
        created.append(part_key)
        parts = []
        offset = 0
        for number, length in enumerate(MULTIPART_PARTS, start=1):
            response = s3.upload_part(
                Bucket=bucket,
                Key=part_key,
                UploadId=upload["UploadId"],
                PartNumber=number,
                Body=body[offset : offset + length],
                ChecksumAlgorithm=algorithm.value.upper(),
            )
            parts.append(
                {
                    "ETag": response["ETag"],
                    "PartNumber": number,
                    response_key: response[response_key],
                }
            )
            offset += length
        s3.complete_multipart_upload(
            Bucket=bucket,
            Key=part_key,
            UploadId=upload["UploadId"],
            MultipartUpload={"Parts": parts},
        )

        head = s3.head_object(Bucket=bucket, Key=part_key, ChecksumMode="ENABLED")
        stored = head.get(response_key, "")
        case = f"{NAME}.multipart.{algorithm.value}"

        yield assert_that(
            f"{case}.aws_marks_it_composite",
            NAME,
            Tier.aws,
            head.get("ChecksumType") == "COMPOSITE"
            and _strip_part_count(stored) != stored,
            f"expected COMPOSITE with a -N suffix, got "
            f"type={head.get('ChecksumType')!r} value={stored!r}",
            parts=len(MULTIPART_PARTS),
        )

        local = workdir / "multipart.bin"
        local.write_bytes(body)
        # Partition the way the uploader did: our composite is only comparable
        # at the part size S3 was given.
        with chunking(PART_SIZE, corpus.READ_BUFFER):
            ours = compute_checksum_localfs(str(local), algorithm)

        yield compare(
            f"{case}.our_composite_equals_aws",
            NAME,
            Tier.aws,
            ours.s3_composite_base64,
            _strip_part_count(stored),
            note=f"composite over {len(MULTIPART_PARTS)} parts of {PART_SIZE} bytes",
        )
        yield compare(
            f"{case}.chunk_count",
            NAME,
            Tier.aws,
            len(ours.chunks),
            len(MULTIPART_PARTS),
        )
        yield assert_that(
            f"{case}.composite_is_not_the_whole_object",
            NAME,
            Tier.aws,
            ours.merkle_root != ours.file_hash,
            "a 3-part composite must differ from the whole-object digest",
        )
        # The protection: a composite must never be offered as a stored digest.
        offered = _fetch_all_s3_stored_checksums(bucket, part_key, s3)
        yield assert_that(
            f"{case}.composite_is_refused_as_stored",
            NAME,
            Tier.aws,
            algorithm not in offered,
            f"a COMPOSITE {algorithm.value} was offered as a whole-object digest: "
            f"{offered.get(algorithm)}",
        )


def _rejected_algorithms(ctx, s3, bucket, prefix) -> Iterator[Check]:
    """S3 must reject exactly the algorithms we classify as non-native."""
    for algorithm in sorted(_NON_S3_NATIVE_ALGORITHMS):
        try:
            s3.put_object(
                Bucket=bucket,
                Key=f"{prefix}/rejected/{algorithm.value}",
                Body=b"x",
                ChecksumAlgorithm=algorithm.value.upper(),
            )
        except Exception as exc:
            yield assert_that(
                f"{NAME}.rejected.{algorithm.value}",
                NAME,
                Tier.aws,
                True,
                "",
                error=type(exc).__name__,
            )
        else:
            # If this ever passes, _S3_NATIVE_RESPONSE_KEY is out of date and we
            # are downloading objects S3 could have checksummed for us.
            yield assert_that(
                f"{NAME}.rejected.{algorithm.value}",
                NAME,
                Tier.aws,
                False,
                f"S3 accepted {algorithm.value}, which we classify as non-native",
            )


def _folder(ctx, s3, bucket, prefix, workdir: Path, put) -> Iterator[Check]:
    """
    A prefix of natively-checksummed objects must assemble without downloading,
    and land on the same root a local copy of the same tree produces.
    """
    algorithm = Algorithm.crc32
    tree = {"a.bin": 1_000, "nested/b.bin": 2_048, "nested/deep/c.bin": 7}
    folder_prefix = f"{prefix}/folder/"

    local_root = workdir / "folder"
    for relative, size in sorted(tree.items()):
        body = corpus.content(f"aws/folder/{relative}", size)
        put(
            f"{folder_prefix}{relative}",
            body,
            ChecksumAlgorithm=algorithm.value.upper(),
        )
        target = local_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

    expected = compute_checksum_localfs(str(local_root), algorithm)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # compute_if_no_s3_checksum=False proves the stored checksums were used:
        # if any child had to be downloaded, this would skip instead.
        detected = for_location(
            f"s3://{bucket}/{folder_prefix}",
            AssetType.folder,
            StoragePlatform.s3,
            algorithm=None,
            s3_client=s3,
            compute_if_no_s3_checksum=False,
        )

    yield assert_that(
        f"{NAME}.folder.auto_detect_used_stored_children",
        NAME,
        Tier.aws,
        bool(detected),
        f"folder produced no checksum without downloads: "
        f"{[str(w.message) for w in caught]}",
    )
    yield compare(
        f"{NAME}.folder.algorithm", NAME, Tier.aws, detected.algorithm, algorithm
    )
    yield compare(
        f"{NAME}.folder.root_matches_local_copy",
        NAME,
        Tier.aws,
        detected.value,
        expected.content_digest,
        note="an S3 prefix and a local copy of the same tree must agree",
    )
    yield compare(
        f"{NAME}.folder.total_size",
        NAME,
        Tier.aws,
        detected.total_size,
        sum(tree.values()),
        note="listing sizes must total the folder without any download",
    )
