"""Shared config + client bootstrap for the bundled catalog scripts.

Prefers the installed ``catalog_client`` SDK. If it isn't installed, falls back
to a tiny standard-library REST client (``urllib``) covering the read endpoints
the scripts need — so a script runs with **no install**. Either surface reads
the token from the environment and sends it as a request *header*; it is never
placed on a command line, so (unlike a ``curl`` invocation) it can't leak into
the process list or shell history.

    CATALOG_API_URL    base URL; defaults to DEFAULT_API_URL when unset.
    CATALOG_API_TOKEN  API token; required, no default — issue one at
                       <catalog>/tokens in a logged-in browser (SSO-gated).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace
from typing import Any, NoReturn

DEFAULT_API_URL = "https://datacatalog.prod-sci-data.prod.czi.team/"
DEFAULT_TIMEOUT = 30.0

# Enum vocabularies, duplicated here so a script can validate CLI choices with
# no SDK installed. Keep in sync with catalog_client.models.dataset.
MODALITIES = ("imaging", "sequencing", "mass spec", "unknown")
SORTS = ("relevance", "alphabetical", "last_modified", "newest", "oldest")
DEFAULT_SORT = "relevance"

EXIT_ERROR = 1
EXIT_USAGE = 2

try:  # reuse the SDK's error type when installed so callers catch one thing
    from catalog_client.exceptions import CatalogError
except ImportError:

    class CatalogError(Exception):  # type: ignore[no-redef]
        """Raised by the stdlib REST fallback on a failed request."""


def usage_error(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(EXIT_USAGE)


def _resolve_config() -> tuple[str, str]:
    """URL (with production default) + token (required); token read from env."""
    url = os.environ.get("CATALOG_API_URL") or DEFAULT_API_URL
    token = os.environ.get("CATALOG_API_TOKEN")
    if not token:
        usage_error(
            "CATALOG_API_TOKEN is not set. Issue a token at "
            f"{url.rstrip('/')}/tokens (open it in a logged-in browser), then set "
            "CATALOG_API_TOKEN in your environment."
        )
    return url, token


# ------------------------------------------------- stdlib REST fallback client


def _param(value: Any) -> Any:
    """Serialize a query param as the API expects: enum -> value, bool -> lowercase."""
    value = getattr(value, "value", value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _page(data: dict) -> SimpleNamespace:
    """Wrap a paginated JSON body so ``.results`` items expose attribute access."""
    results = [SimpleNamespace(**row) for row in data.get("results", [])]
    return SimpleNamespace(
        results=results,
        total=data.get("total"),
        limit=data.get("limit"),
        offset=data.get("offset"),
    )


class _RestDatasets:
    def __init__(self, request):
        self._request = request

    def search(self, *, q=None, limit=10, **filters):
        return _page(
            self._request("/api/datasets/search/", {"q": q, "limit": limit, **filters})
        )

    def list(self, *, offset=0, limit=100, **filters):
        return _page(
            self._request(
                "/api/datasets/", {"offset": offset, "limit": limit, **filters}
            )
        )

    def get(self, dataset_id):
        return SimpleNamespace(**self._request(f"/api/datasets/{dataset_id}", {}))


class _RestClient:
    """Minimal read-only catalog client over ``urllib`` — no third-party deps."""

    def __init__(self, base_url: str, token: str, timeout: float = DEFAULT_TIMEOUT):
        self._base = base_url.rstrip("/")
        # The token travels as a header, never as a command-line argument.
        self._headers = {"X-catalog-api-token": token, "Accept": "application/json"}
        self._timeout = timeout
        self.datasets = _RestDatasets(self._request)

    def _request(self, path: str, params: dict) -> dict:
        clean = {k: _param(v) for k, v in params.items() if v is not None}
        query = urllib.parse.urlencode(clean, doseq=True)
        url = f"{self._base}{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(url, headers=self._headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise CatalogError(f"HTTP {exc.code} {exc.reason} for {path}") from exc
        except urllib.error.URLError as exc:
            raise CatalogError(f"request to {path} failed: {exc.reason}") from exc

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ------------------------------------------------------ SDK wrapper (if present)


def _as_enums(filters: dict) -> dict:
    """Turn the string filters the scripts pass into the enums the SDK requires."""
    from catalog_client.models.dataset import DatasetModality, DatasetSortOption

    out = dict(filters)
    if out.get("modality") is not None:
        out["modality"] = DatasetModality(out["modality"])
    if out.get("sort") is not None:
        out["sort"] = DatasetSortOption(out["sort"])
    return out


class _SdkDatasets:
    def __init__(self, datasets):
        self._datasets = datasets

    def search(self, *, q=None, limit=10, **filters):
        return self._datasets.search(q=q, limit=limit, **_as_enums(filters))

    def list(self, *, offset=0, limit=100, **filters):
        return self._datasets.list(offset=offset, limit=limit, **_as_enums(filters))

    def get(self, dataset_id):
        return self._datasets.get(dataset_id)


class _SdkClient:
    """Wraps the installed CatalogClient so callers pass plain-string filters."""

    def __init__(self, sdk):
        self._sdk = sdk
        self.datasets = _SdkDatasets(sdk.datasets)

    def __enter__(self):
        self._sdk.__enter__()
        return self

    def __exit__(self, *exc):
        return self._sdk.__exit__(*exc)


def get_client():
    """Return a read client: the wrapped SDK if installed, else the urllib fallback."""
    url, token = _resolve_config()
    try:
        from catalog_client.client.catalog import CatalogClient
    except ImportError:
        return _RestClient(url, token)
    return _SdkClient(CatalogClient(base_url=url, api_token=token))
