"""
Bounded, deterministic concurrency for the checksum walks.

Two properties matter here and neither comes free from concurrent.futures:

Determinism — results are yielded in input order, and an item's exception is
raised at that item's position. A folder digest depends on the order children
are inserted, and a failure message should not depend on which thread lost a
race, so "whichever finished first" is never an acceptable ordering.

Boundedness — futures are submitted through a sliding window rather than all at
once. ThreadPoolExecutor.map submits every future before yielding the first
result, which for a million-object prefix costs hundreds of megabytes of
scheduling state before any work is reported.
"""

import logging
import os
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from itertools import islice
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

# Local hashing is CPU-bound and measured scaling plateaus between 4 and 8
# threads, then declines: past that point the GIL handoff and the filesystem's
# own locking cost more than the extra parallelism returns.
DEFAULT_LOCAL_WORKERS = 8

# S3 is latency-bound, so more workers would help — but a stock boto3 client
# caps its connection pool at 10, and botocore leaves urllib3 at block=False,
# which means an over-subscribed pool silently closes and re-opens connections
# rather than queueing. Staying under the default leaves room for the paginator.
DEFAULT_S3_WORKERS = 8

# Futures held in flight per worker. Enough that a worker never idles waiting
# for the consumer to advance, small enough that the queue stays bounded.
_WINDOW_PER_WORKER = 4


def ordered_map(
    fn: Callable[[T], R], items: Iterable[T], max_workers: int
) -> Iterator[R]:
    """
    Apply `fn` across `items` concurrently, yielding results in input order.

    An exception raised for item i surfaces when the consumer reaches i, with
    the items before it already yielded. Callers that consume everything see
    the first failure in input order; callers that stop early (the S3 folder
    scan does) see exactly what a serial loop would have seen at that point.
    """
    if max_workers <= 1:
        # Not merely an optimisation: no pool means no threads, so a caller
        # asking for serial execution gets the original call stack in
        # tracebacks and the original behaviour under warnings filters.
        for item in items:
            yield fn(item)
        return

    remaining = iter(items)
    pending: deque[Future[R]] = deque()
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        for item in islice(remaining, max_workers * _WINDOW_PER_WORKER):
            pending.append(pool.submit(fn, item))

        while pending:
            # .result() re-raises here, at this item's position in the output.
            yield pending.popleft().result()
            for item in islice(remaining, 1):
                pending.append(pool.submit(fn, item))
    finally:
        # cancel_futures so an exception, or a consumer that stops early, does
        # not block on a full window of work whose results nobody will read.
        pool.shutdown(wait=False, cancel_futures=True)


def local_workers(requested: int | None) -> int:
    """Worker count for local filesystem hashing."""
    if requested is not None:
        return max(1, requested)
    try:
        # sched_getaffinity, not cpu_count: it honours taskset and cgroup CPU
        # limits, so a container pinned to 2 cores does not spawn 8 threads.
        available = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except AttributeError:  # macOS and Windows do not have it
        available = os.cpu_count() or 1
    return max(1, min(DEFAULT_LOCAL_WORKERS, available))


def s3_workers(s3, requested: int | None) -> int:
    """
    Worker count for S3 requests, clamped to the client's own connection pool.

    Exceeding max_pool_connections does not block or error — botocore leaves
    urllib3 at block=False, so urllib3 closes and discards each excess
    connection and logs "Connection pool is full". The work still completes,
    having paid a fresh TLS handshake per request. Clamping keeps that silent
    slowdown from happening to a caller who passed us their own client.
    """
    config = getattr(getattr(s3, "meta", None), "config", None)
    cap = getattr(config, "max_pool_connections", None)
    # Test doubles report a Mock here rather than an int; fall back to the
    # default instead of comparing against something meaningless.
    limit = cap if isinstance(cap, int) and cap > 0 else DEFAULT_S3_WORKERS
    wanted = DEFAULT_S3_WORKERS if requested is None else requested
    workers = max(1, min(wanted, limit))
    if workers < wanted:
        logger.debug(
            "Limiting S3 checksum workers to %d: the client's connection pool "
            "allows %d. Raise max_pool_connections on the client to use more.",
            workers,
            limit,
        )
    return workers
