"""
A hand-built S3 double for the listing hints moto cannot produce.

moto 5.1.22 reports ``ChecksumAlgorithm: ['CRC32']`` on every object under a
prefix — including objects uploaded with no ChecksumAlgorithm at all — and
omits ``ChecksumType`` entirely. So the decisions that turn on those fields
(a COMPOSITE checksum in the listing, an explicitly empty algorithm list, a
multipart ETag, or the claim that a HeadObject was *not* issued) cannot be
exercised through ``mock_aws``: it would agree with any implementation.

This stub states each field explicitly, counts every request, and can gate one
key's request on an event so concurrency can be asserted deterministically
rather than by sleeping. Keep moto for the end-to-end paths it does model.
"""

import base64
import io
import threading
from dataclasses import dataclass, field

from catalog_client.utils.checksum.algorithm import Algorithm, new_hasher
from catalog_client.utils.checksum.s3 import (
    _S3_NATIVE_NAME,
    _S3_NATIVE_RESPONSE_KEY,
)

# Sentinel distinguishing "the caller did not set this field" from "the caller
# set it to None", which for ``size`` and ``etag`` are different listings.
_UNSET = object()


def digest_hex(body: bytes, algorithm: Algorithm) -> str:
    """The hex digest `algorithm` produces for `body`."""
    hasher = new_hasher(algorithm)
    hasher.update(body)
    return hasher.hexdigest()


def native_b64(body: bytes, algorithm: Algorithm) -> str:
    """The base64 whole-object checksum S3 would return for `body`."""
    return base64.b64encode(bytes.fromhex(digest_hex(body, algorithm))).decode()


@dataclass
class StubObject:
    """
    One object, described from the two angles S3 describes it from.

    The ``listing_*`` fields are what ListObjectsV2 reports; ``head`` is what
    HeadObject returns. They are set independently on purpose — the whole point
    of the hint model is that the listing may be absent, stale, or coarser than
    the HEAD, and the code must not assume they agree.
    """

    key: str
    body: bytes = b""
    listing_algorithms: list[str] | None = None
    listing_checksum_type: str | None = None
    etag: object = _UNSET
    size: object = _UNSET
    head: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def listing_entry(self) -> dict:
        entry: dict = {"Key": self.key}
        if self.size is not _UNSET:
            if self.size is not None:
                entry["Size"] = self.size
        else:
            entry["Size"] = len(self.body)
        if self.listing_algorithms is not None:
            entry["ChecksumAlgorithm"] = list(self.listing_algorithms)
        if self.listing_checksum_type is not None:
            entry["ChecksumType"] = self.listing_checksum_type
        if self.etag is not _UNSET:
            if self.etag is not None:
                entry["ETag"] = self.etag
        else:
            entry["ETag"] = f'"{self.key}"'
        return entry

    def head_response(self) -> dict:
        response: dict = {"ContentLength": len(self.body), **self.head}
        if self.metadata:
            response["Metadata"] = dict(self.metadata)
        # A None value removes the field, which is how a test says "this HEAD
        # did not report a ContentLength" rather than "it reported nothing".
        return {k: v for k, v in response.items() if v is not None}

    def with_metadata(self, algorithm: Algorithm):
        """Attach a digest in user metadata, as our uploader writes it."""
        self.metadata = {
            **self.metadata,
            f"x-checksum-{algorithm}": digest_hex(self.body, algorithm),
        }
        return self

    def with_native(self, algorithm: Algorithm, checksum_type: str = "FULL_OBJECT"):
        """Attach a real whole-object native checksum, in listing and HEAD."""
        self.listing_algorithms = [_S3_NATIVE_NAME[algorithm]]
        self.listing_checksum_type = checksum_type
        self.head = {
            **self.head,
            _S3_NATIVE_RESPONSE_KEY[algorithm]: native_b64(self.body, algorithm),
            "ChecksumType": checksum_type,
        }
        return self


class _Paginator:
    def __init__(self, stub, page_size: int):
        self._stub = stub
        self._page_size = page_size

    def paginate(self, Bucket: str, Prefix: str):  # noqa: N803 — botocore's shape
        self._stub.list_calls += 1
        matching = [o for o in self._stub.objects if o.key.startswith(Prefix)]
        for start in range(0, max(len(matching), 1), self._page_size):
            page = matching[start : start + self._page_size]
            self._stub.pages_yielded += 1
            yield {"Contents": [o.listing_entry() for o in page]}


class _Config:
    # Above DEFAULT_S3_WORKERS so the stub exercises the real default rather
    # than silently clamping every walk. Per-instance so a test can narrow it.
    def __init__(self, max_pool_connections=40):
        self.max_pool_connections = max_pool_connections


class _Meta:
    def __init__(self, max_pool_connections=40):
        self.config = _Config(max_pool_connections)


class StubS3:
    """
    A minimal S3 client: list, head, get, with per-request bookkeeping.

    ``heads`` and ``gets`` record keys in completion order, so a test asserts
    on counts or membership rather than ordering, which concurrency leaves
    unspecified. ``gate`` blocks a named key's request until its event is set,
    which is how the removal of the HEAD-before-GET barrier is demonstrated
    without a sleep.
    """

    def __init__(
        self,
        objects: list[StubObject],
        page_size: int = 1000,
        max_pool_connections: int = 40,
    ):
        self.meta = _Meta(max_pool_connections)
        self.objects = objects
        self._by_key = {o.key: o for o in objects}
        self._page_size = page_size
        self.list_calls = 0
        self.pages_yielded = 0
        self.heads: list[str] = []
        self.gets: list[str] = []
        self._lock = threading.Lock()
        self.head_gate: dict[str, threading.Event] = {}
        self.get_gate: dict[str, threading.Event] = {}
        self.head_entered = threading.Event()

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        return _Paginator(self, self._page_size)

    def head_object(self, Bucket, Key, **kwargs):  # noqa: N803 — botocore's shape
        with self._lock:
            self.heads.append(Key)
        self.head_entered.set()
        if (gate := self.head_gate.get(Key)) is not None:
            gate.wait(timeout=10)
        return self._by_key[Key].head_response()

    def get_object(self, Bucket, Key, **kwargs):  # noqa: N803 — botocore's shape
        with self._lock:
            self.gets.append(Key)
        if (gate := self.get_gate.get(Key)) is not None:
            gate.wait(timeout=10)
        obj = self._by_key[Key]
        return {"Body": io.BytesIO(obj.body), "ContentLength": len(obj.body)}
