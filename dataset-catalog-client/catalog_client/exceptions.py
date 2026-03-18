"""
Exceptions raised by the Catalog client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from catalog_client.models.dataset import DatasetRef


class CatalogError(Exception):
    """Base exception for all Catalog client errors."""


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


def raise_for_status(response: httpx.Response) -> None:
    """Raise an appropriate CatalogError for non-2xx responses."""
    if response.status_code == 401:
        raise AuthenticationError(401, response.json().get("detail", "Unauthorized"))
    if response.status_code == 404:
        raise NotFoundError(404, response.json().get("detail", "Not found"))
    if response.status_code == 422:
        raise ValidationError(422, response.json().get("detail"))
    if response.status_code >= 500:
        raise CatalogServerError(response.status_code, response.json().get("detail"))
    response.raise_for_status()
