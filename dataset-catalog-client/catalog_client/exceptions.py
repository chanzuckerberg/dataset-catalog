"""
Exceptions raised by the Catalog client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from catalog_client.models.copy import CopyErrorCode

if TYPE_CHECKING:
    from catalog_client.models.dataset import DatasetRef


class CatalogError(Exception):
    """Base exception for all Catalog client errors."""


class CatalogUsageError(CatalogError, ValueError):
    """Caller passed arguments the client can reject without a round trip.

    Deliberately also a `ValueError`, so the guards that historically raised
    one stay catchable that way. The distinct type is what lets the CLI
    report these as usage errors without also swallowing an unrelated
    `ValueError` — notably `pydantic.ValidationError`, which subclasses it
    and signals a genuine response-parsing failure, not caller error.
    """


class CatalogHTTPError(CatalogError):
    """Base for HTTP-layer errors. Carries status_code and response body."""

    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class AuthenticationError(CatalogHTTPError):
    """401 — missing or invalid API token."""


class NotFoundError(CatalogHTTPError):
    """404 — resource not found or tombstoned."""


class ValidationError(CatalogHTTPError):
    """422 — request payload failed server-side validation."""


class CatalogServerError(CatalogHTTPError):
    """5xx — unexpected server error."""


class CopyError(CatalogHTTPError):
    """A copy was refused, with the machine-readable reason the route returns.

    The copy route answers a refusal with an object `detail` rather than the
    string every other route uses, because the caller is expected to branch
    on `code` and to retry only when `retryable` says a retry can help. The
    code is kept as the raw string when the server sends one this client
    does not know, so an unrecognised reason still reaches the caller
    instead of failing to parse.
    """

    def __init__(self, status_code: int, detail: dict) -> None:
        raw_code = detail.get("code")
        try:
            self.code: CopyErrorCode | str | None = CopyErrorCode(raw_code)
        except ValueError:
            self.code = raw_code
        self.message: str = detail.get("message", "")
        self.retryable: bool = bool(detail.get("retryable"))
        super().__init__(status_code, detail)


class CatalogConnectionError(CatalogError):
    """Network-level failure (wraps httpx transport errors)."""


class LineageResolutionError(CatalogError):
    """A DatasetRef could not be resolved to a unique dataset UUID."""

    def __init__(self, ref: DatasetRef, reason: str) -> None:
        self.ref = ref
        super().__init__(
            f"Could not resolve DatasetRef(canonical_id={ref.canonical_id!r}, "
            f"version={ref.version!r}, project={ref.project!r}): {reason}"
        )


class DuplicateDatasetError(CatalogError):
    """A dataset with the same canonical_id, version, and project already exists."""

    def __init__(self, ref: DatasetRef) -> None:
        self.ref = ref
        super().__init__(
            f"Dataset already exists: {ref!r}. "
            f"Use update_if_exists=True to update or error_on_duplicate=False to skip."
        )


def _structured_detail(response: httpx.Response) -> dict | None:
    """Return the `detail` object of a refusal that carries one, else None."""
    try:
        body = response.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict) and "code" in detail and "retryable" in detail:
        return detail
    return None


def raise_for_status(response: httpx.Response) -> None:
    """Raise an appropriate CatalogError for non-2xx responses."""
    if response.is_success:
        return
    structured = _structured_detail(response)
    if structured is not None:
        raise CopyError(response.status_code, structured)
    if response.status_code == 401:
        raise AuthenticationError(401, response.json().get("detail", "Unauthorized"))
    if response.status_code == 404:
        raise NotFoundError(404, response.json().get("detail", "Not found"))
    if response.status_code == 422:
        raise ValidationError(422, response.json().get("detail"))
    if response.status_code >= 500:
        raise CatalogServerError(response.status_code, response.json().get("detail"))
    response.raise_for_status()
