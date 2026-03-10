"""
Exceptions raised by the Catalog client.
"""
import httpx


class CatalogError(Exception):
    """Base exception for all Catalog client errors."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class AuthenticationError(CatalogError):
    """Raised when the API token is missing or invalid (401)."""

class NotFoundError(CatalogError):
    """Raised when the requested resource does not exist (404)."""

class RecordValidationError(CatalogError):
    """Raised on unexpected server errors (5xx)."""

class CatalogServerError(CatalogError):
    """Raised on unexpected server errors (5xx)."""


def raise_for_status(response: httpx.Response) -> None:
    if response.status_code == 401:
        raise AuthenticationError(401, response.json().get("detail", "Unauthorized"))
    if response.status_code == 404:
        raise NotFoundError(404, response.json().get("detail", "Not found"))
    if response.status_code == 422:
        raise RecordValidationError(422, response.json().get("detail", "Not found"))
    if response.status_code >= 500:
        raise CatalogServerError(response.status_code, f"Server error: {response.json()}")
    response.raise_for_status()
