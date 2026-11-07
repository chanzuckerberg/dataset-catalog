"""run_batch — isolated, concurrency-capped registration of many items."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")

_logger = logging.getLogger(__name__)


@dataclass
class BatchReport:
    succeeded: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        head = f"{len(self.succeeded)} registered, {len(self.failed)} failed"
        if not self.failed:
            return head
        return head + ": " + ", ".join(f"{k} ({msg})" for k, msg in self.failed)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


def _describe(exc: Exception) -> str:
    # Collapse multi-line messages (pydantic's, notably) so each failure stays one log line.
    return f"{type(exc).__name__}: {' '.join(str(exc).split())}"


def run_batch(
    items: Iterable[T],
    handle: Callable[[T], str],
    *,
    key: Callable[[T], str] = str,
    max_workers: int = 4,
    logger: logging.Logger | None = None,
) -> BatchReport:
    log = logger or _logger
    report = BatchReport()
    # Keeps every worker fed while never reading `items` far ahead of them.
    window = max_workers * 2
    in_flight: dict[Future[str], str] = {}

    def fail(item_key: str, exc: Exception) -> None:
        message = _describe(exc)
        report.failed.append((item_key, message))
        log.error("%s failed: %s", item_key, message)

    def record(done: set[Future[str]]) -> None:
        for future in done:
            item_key = in_flight.pop(future)
            exc = future.exception()
            if exc is None:
                report.succeeded.append((item_key, future.result()))
            elif isinstance(exc, Exception):
                fail(item_key, exc)
            else:
                raise exc

    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        for index, item in enumerate(items):
            try:
                item_key = key(item)
            except Exception as exc:
                fail(f"item[{index}]", exc)
                continue
            in_flight[pool.submit(handle, item)] = item_key
            if len(in_flight) >= window:
                done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                record(done)
        while in_flight:
            done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            record(done)
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown()
    return report
