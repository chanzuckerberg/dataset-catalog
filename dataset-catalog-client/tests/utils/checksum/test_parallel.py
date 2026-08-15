"""Tests for the bounded, order-preserving parallel map.

The two properties worth testing here are the ones a folder digest depends on.
Ordering: children must be combined in input order regardless of which thread
finishes first, or the same tree hashes differently run to run. Boundedness:
the window must not degenerate into submitting everything up front, which is
what ThreadPoolExecutor.map does and why this module exists.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from catalog_client.utils.checksum._parallel import (
    DEFAULT_LOCAL_WORKERS,
    DEFAULT_S3_WORKERS,
    local_workers,
    ordered_map,
    s3_workers,
)

# ── Ordering ──────────────────────────────────────────────────────────────────


def test_results_follow_input_order_not_completion_order():
    # Later items finish first, so anything relying on completion order
    # produces the reverse of this.
    def slow_descending(i):
        time.sleep((10 - i) * 0.005)
        return i

    assert list(ordered_map(slow_descending, range(10), max_workers=4)) == list(
        range(10)
    )


def test_empty_input_yields_nothing():
    assert list(ordered_map(lambda i: i, [], max_workers=4)) == []


def test_single_worker_runs_inline_on_the_calling_thread():
    # Serial is not just max_workers=1 on a pool: it must not spawn a thread at
    # all, so tracebacks keep the caller's stack and warnings filters still apply.
    main = threading.get_ident()
    threads = list(ordered_map(lambda i: threading.get_ident(), range(5), 1))
    assert threads == [main] * 5


def test_work_actually_runs_concurrently():
    # The barrier only clears if four calls are in flight at once, so this
    # fails rather than hangs if the map silently serialised.
    barrier = threading.Barrier(4, timeout=10)

    def wait_for_others(i):
        barrier.wait()
        return i

    assert list(ordered_map(wait_for_others, range(4), max_workers=4)) == [0, 1, 2, 3]


# ── Failure position ──────────────────────────────────────────────────────────


def _raise_at(*failing):
    def fn(i):
        if i in failing:
            raise ValueError(f"item {i}")
        return i

    return fn


def test_raises_the_first_failure_in_input_order_not_the_first_to_occur():
    # Item 2 is slow, so item 4 fails first in wall-clock terms. Input order is
    # what must decide, or the error message depends on thread scheduling.
    def fn(i):
        if i == 2:
            time.sleep(0.05)
            raise ValueError("item 2")
        if i == 4:
            raise ValueError("item 4")
        return i

    with pytest.raises(ValueError, match="item 2"):
        list(ordered_map(fn, range(6), max_workers=4))


def test_items_before_the_failure_are_yielded_first():
    gen = ordered_map(_raise_at(2), range(6), max_workers=4)
    assert [next(gen), next(gen)] == [0, 1]
    with pytest.raises(ValueError, match="item 2"):
        next(gen)


def test_a_consumer_that_stops_early_never_sees_a_later_failure():
    # The S3 folder scan stops as soon as a child has no checksum. It must see
    # exactly what a serial loop would have seen at that point -- not an
    # exception raised by an object it never got to.
    gen = ordered_map(_raise_at(3), range(6), max_workers=4)
    assert [next(gen), next(gen)] == [0, 1]
    gen.close()  # must not raise, and must not hang


# ── Boundedness ───────────────────────────────────────────────────────────────


def test_futures_are_submitted_through_a_sliding_window(monkeypatch):
    submitted = []
    real_submit = ThreadPoolExecutor.submit

    def counting_submit(self, fn, *args, **kwargs):
        submitted.append(args[0] if args else None)
        return real_submit(self, fn, *args, **kwargs)

    monkeypatch.setattr(ThreadPoolExecutor, "submit", counting_submit)

    workers = 2
    gen = ordered_map(lambda i: i, range(10_000), max_workers=workers)
    next(gen)  # consume exactly one result
    gen.close()

    # One window up front, plus the single top-up that follows the first yield.
    assert len(submitted) <= workers * 4 + 1
    assert len(submitted) < 10_000  # the failure this guards against


# ── Worker counts ─────────────────────────────────────────────────────────────


def test_local_workers_honours_an_explicit_request():
    assert local_workers(3) == 3
    assert local_workers(64) == 64  # explicit beats the default cap


def test_local_workers_floors_at_one():
    assert local_workers(0) == 1
    assert local_workers(-4) == 1


def test_local_workers_defaults_within_the_cap():
    assert 1 <= local_workers(None) <= DEFAULT_LOCAL_WORKERS


def test_s3_workers_clamps_to_a_stock_client_pool():
    boto3 = pytest.importorskip("boto3")
    client = boto3.client("s3", region_name="us-east-1")
    assert client.meta.config.max_pool_connections == 10
    # Default stays under the pool; an oversized request is clamped to it.
    assert s3_workers(client, None) == DEFAULT_S3_WORKERS
    assert s3_workers(client, 64) == 10
    assert s3_workers(client, 2) == 2


def test_s3_workers_respects_a_narrowed_client_pool():
    boto3 = pytest.importorskip("boto3")
    botocore_config = pytest.importorskip("botocore.config")
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        config=botocore_config.Config(max_pool_connections=4),
    )
    assert s3_workers(client, None) == 4
    assert s3_workers(client, 8) == 4


def test_s3_workers_falls_back_when_the_client_reports_no_usable_pool():
    # Test doubles answer every attribute with a Mock, so the pool size is not
    # an int and must not be compared against.
    assert s3_workers(MagicMock(), None) == DEFAULT_S3_WORKERS
    assert s3_workers(MagicMock(), 3) == 3
    assert s3_workers(object(), None) == DEFAULT_S3_WORKERS
