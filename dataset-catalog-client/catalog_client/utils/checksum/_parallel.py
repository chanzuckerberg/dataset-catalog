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

# Spare connections kept above the worker count on a client we build ourselves,
# so the paginator driving a walk never contends with a full set of workers.
_POOL_HEADROOM = 8


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
    # Named so the per-file log lines identify their worker as "checksum_3"
    # rather than the default "ThreadPoolExecutor-0_3", which also renumbers its
    # pool counter per executor and so repeats across successive walks.
    pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="checksum")
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


def requested_s3_workers(s3_workers: int | None, hash_max_workers: int | None) -> int:
    """
    Resolve the two worker knobs into one S3 request budget.

    `is not None` rather than `or`: a caller asking for 0 means "as few as
    possible", and falsiness would silently hand them the hash budget instead
    of the floor of 1.

    Every consumer of the budget resolves it here. `effective_s3_workers` reads
    it to size the pool of threads and `owned_s3_client` to size the pool of
    connections, and the two disagreeing is the silent-slowdown failure
    documented on `owned_s3_client`.
    """
    if s3_workers is not None:
        return max(1, s3_workers)
    if hash_max_workers is not None:
        return max(1, hash_max_workers)
    return DEFAULT_S3_WORKERS


def effective_s3_workers(
    s3, s3_workers: int | None = None, hash_max_workers: int | None = None
) -> int:
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
    wanted = requested_s3_workers(s3_workers, hash_max_workers)
    workers = max(1, min(wanted, limit))
    if workers < wanted:
        logger.debug(
            "Limiting S3 checksum workers to %d: the client's connection pool "
            "allows %d. Raise max_pool_connections on the client to use more.",
            workers,
            limit,
        )
    return workers


def owned_s3_client(s3_workers: int | None = None, hash_max_workers: int | None = None):
    """
    A boto3 S3 client whose connection pool is sized for our own worker count.

    Only for clients we construct: a client passed in by a caller is used as-is
    and `effective_s3_workers` clamps to whatever pool they chose. Lives beside
    `effective_s3_workers` because it is the same policy from the other side — that
    function reads a pool limit, this one writes it, and when the two disagree
    the walk silently pays a TLS handshake per excess request.

    boto3 is imported here rather than at module scope: it pulls in several
    hundred modules, and `import catalog_client` reaches this package
    transitively via catalog_client.utils.
    """
    import boto3
    from botocore.config import Config

    # max(), because max_pool_connections is a cap rather than a
    # preallocation: a floor of the default budget costs nothing and keeps a
    # small explicit request from sizing the pool below what a later caller
    # asks for on the same client.
    budget = requested_s3_workers(s3_workers, hash_max_workers)
    pool = max(DEFAULT_S3_WORKERS, budget) + _POOL_HEADROOM
    return boto3.client("s3", config=Config(max_pool_connections=pool))
