"""RetryPolicy and the httpx transports that apply it."""

from __future__ import annotations

import asyncio
import datetime
import email.utils
import random
import time
from dataclasses import dataclass

import httpx

_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE"})
_IDEMPOTENT_RETRY_STATUSES = frozenset({429, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay: float = 0.5
    max_delay: float = 30.0
    jitter: bool = True


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


async def _asleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _should_retry_status(method: str, status_code: int) -> bool:
    if method in _IDEMPOTENT_METHODS:
        return status_code in _IDEMPOTENT_RETRY_STATUSES
    return status_code == 429


def _should_retry_error(method: str, exc: httpx.TransportError) -> bool:
    if method in _IDEMPOTENT_METHODS:
        return True
    # A POST/PATCH that failed any later than connecting may already have been
    # applied server-side; only a connect failure proves it was never sent.
    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))


def _backoff(policy: RetryPolicy, retry_number: int) -> float:
    delay = min(policy.max_delay, policy.base_delay * 2 ** (retry_number - 1))
    return random.uniform(0, delay) if policy.jitter else delay


def _retry_after(response: httpx.Response, policy: RetryPolicy) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:  # "-0000" parses naive; HTTP-dates are UTC
            when = when.replace(tzinfo=datetime.timezone.utc)
        seconds = (when - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    return min(policy.max_delay, max(0.0, seconds))


def _next_delay(
    policy: RetryPolicy,
    method: str,
    attempt: int,
    response: httpx.Response | None = None,
    exc: httpx.TransportError | None = None,
) -> float | None:
    """Seconds to wait before the next attempt, or None to stop retrying."""
    if attempt >= policy.max_attempts:
        return None
    if exc is not None:
        return _backoff(policy, attempt) if _should_retry_error(method, exc) else None
    assert response is not None
    if not _should_retry_status(method, response.status_code):
        return None
    server_delay = _retry_after(response, policy)
    return _backoff(policy, attempt) if server_delay is None else server_delay


class RetryTransport(httpx.BaseTransport):
    def __init__(self, transport: httpx.BaseTransport, policy: RetryPolicy) -> None:
        self._transport = transport
        self._policy = policy

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        attempt = 1
        while True:
            try:
                response = self._transport.handle_request(request)
            except httpx.TransportError as exc:
                delay = _next_delay(self._policy, request.method, attempt, exc=exc)
                if delay is None:
                    raise
            else:
                delay = _next_delay(
                    self._policy, request.method, attempt, response=response
                )
                if delay is None:
                    return response
                response.close()
            _sleep(delay)
            attempt += 1

    def close(self) -> None:
        self._transport.close()


class AsyncRetryTransport(httpx.AsyncBaseTransport):
    def __init__(
        self, transport: httpx.AsyncBaseTransport, policy: RetryPolicy
    ) -> None:
        self._transport = transport
        self._policy = policy

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        attempt = 1
        while True:
            try:
                response = await self._transport.handle_async_request(request)
            except httpx.TransportError as exc:
                delay = _next_delay(self._policy, request.method, attempt, exc=exc)
                if delay is None:
                    raise
            else:
                delay = _next_delay(
                    self._policy, request.method, attempt, response=response
                )
                if delay is None:
                    return response
                await response.aclose()
            await _asleep(delay)
            attempt += 1

    async def aclose(self) -> None:
        await self._transport.aclose()
