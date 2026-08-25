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
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace
from typing import Any, NoReturn

DEFAULT_API_URL = "https://datacatalog.prod-sci-data.prod.czi.team/"
DEFAULT_TIMEOUT = 30.0

# Candidate OpenAPI-spec locations, most likely first. The API is in flux;
# probing these lets a relocated spec (or endpoint) degrade to one extra
# request instead of a broken script.
SPEC_PATHS = (
    "/api/meta/openapi.json",
    "/api/openapi.json",
    "/openapi.json",
)

# Dataset routes as of authoring — the fast path. If one of them 404s/405s the
# REST client re-resolves the current routes from the live spec (once) and
# retries, so an endpoint move degrades to one extra round-trip.
DEFAULT_DATASET_ROUTES = {
    "search": "/api/datasets/search/",
    "list": "/api/datasets/",
    "get": "/api/datasets/{id}",
}

# The ``{id}``-style placeholder in a route template, whatever it is named.
_PATH_PARAM_RE = re.compile(r"\{[^}]+\}")

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


class _HttpError(CatalogError):  # type: ignore[misc, valid-type]
    """A request that reached the API and came back non-2xx.

    Carries the status code so the retry logic can tell a moved route (404/405)
    from a connection failure, which raises a bare ``CatalogError`` instead.
    """

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


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
    def __init__(self, call):
        self._call = call

    def search(self, *, q=None, limit=10, **filters):
        return _page(self._call("search", {"q": q, "limit": limit, **filters}))

    def list(self, *, offset=0, limit=100, **filters):
        return _page(self._call("list", {"offset": offset, "limit": limit, **filters}))

    def get(self, dataset_id):
        return SimpleNamespace(**self._call("get", {}, path_arg=dataset_id))


class _RestClient:
    """Minimal read-only catalog client over ``urllib`` — no third-party deps.

    Dataset routes start from ``DEFAULT_DATASET_ROUTES``; on the first
    404/405 the client re-resolves them from the live OpenAPI spec and
    retries, so an endpoint move self-heals instead of breaking the script.
    """

    def __init__(self, base_url: str, token: str, timeout: float = DEFAULT_TIMEOUT):
        self._base = base_url.rstrip("/")
        # The token travels as a header, never as a command-line argument.
        self._headers = {"X-catalog-api-token": token, "Accept": "application/json"}
        self._timeout = timeout
        self._routes = dict(DEFAULT_DATASET_ROUTES)
        self._rediscovered = False  # spec is consulted at most once per client
        self.datasets = _RestDatasets(self._call)

    def _request(self, path: str, params: dict) -> dict:
        clean = {k: _param(v) for k, v in params.items() if v is not None}
        query = urllib.parse.urlencode(clean, doseq=True)
        url = f"{self._base}{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(url, headers=self._headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise _HttpError(
                f"HTTP {exc.code} {exc.reason} for {path}", exc.code
            ) from exc
        except urllib.error.URLError as exc:
            raise CatalogError(f"request to {path} failed: {exc.reason}") from exc

    def _path(self, role: str, path_arg=None) -> str:
        """The concrete path for a dataset role, with any ``{param}`` filled in."""
        route = self._routes[role]
        if path_arg is not None:
            quoted = urllib.parse.quote(str(path_arg), safe="")
            route = _PATH_PARAM_RE.sub(quoted, route)
        return route

    def _call(self, role: str, params: dict, path_arg=None) -> dict:
        """Request a dataset route by role, re-resolving from the spec on 404/405.

        A 404 on the ``get`` route can also mean a genuinely missing id, so the
        retry only happens when rediscovery yields a *different* path; otherwise
        the original error propagates untouched. A connection failure raises a
        bare ``CatalogError`` and so never reaches this handler.
        """
        stale = self._path(role, path_arg)
        try:
            return self._request(stale, params)
        except _HttpError as exc:
            if exc.status not in (404, 405) or self._rediscovered:
                raise
            self._rediscover()
            fresh = self._path(role, path_arg)
            if fresh == stale:  # e.g. a missing id, not a moved route
                raise
            return self._request(fresh, params)

    def _rediscover(self) -> None:
        """Refresh dataset routes from the live OpenAPI spec (best-effort)."""
        self._rediscovered = True
        found = probe_spec(self, [])  # diagnostics discarded: this is best-effort
        if found:
            self._routes.update(_dataset_routes_from_spec(found[0]))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def probe_spec(client: _RestClient, errors: list[str]) -> tuple[dict, str] | None:
    """Return ``(spec, path)`` from the first candidate that yields an OpenAPI doc.

    The single definition of what counts as a usable spec, shared by the
    self-healing client and ``api_map.py`` so the two can't drift apart.
    ``errors`` collects a per-candidate diagnostic; pass a throwaway list to
    ignore them.
    """
    for path in SPEC_PATHS:
        try:
            spec = client._request(path, {})
        except CatalogError as exc:
            errors.append(str(exc))
            continue
        except ValueError:
            # An SSO login page comes back as HTML; treat it like a miss.
            errors.append(f"{path}: non-JSON response (SSO redirect?)")
            continue
        if isinstance(spec, dict) and "paths" in spec:
            return spec, path
        errors.append(f"{path}: JSON but not an OpenAPI document")
    return None


def _dataset_routes_from_spec(spec: dict) -> dict:
    """Map the spec's dataset GET paths onto the search/list/get roles.

    Classification is structural, so a rename survives: a single trailing
    ``{param}`` segment is the detail route, the bare collection path is the
    list route, and a parameterless verb sub-path (``/search/``, or whatever
    it is called this week) is the search route.
    """
    routes: dict[str, str] = {}
    verb_paths: list[str] = []
    paths = spec.get("paths", {})
    for path in sorted(paths):
        if "get" not in {m.lower() for m in paths[path]}:
            continue
        if "dataset" not in path or "collection" in path or "lineage" in path:
            continue
        if "{" in path:
            # only the plain detail route (a single trailing {param} segment),
            # not sub-resources like /{id}/history.
            if path.count("{") == 1 and re.fullmatch(r".*/\{[^}]+\}/?", path):
                routes.setdefault("get", path)
        elif re.fullmatch(r".*/datasets/?", path):
            routes.setdefault("list", path)
        else:
            verb_paths.append(path)
    named = [p for p in verb_paths if "search" in p]
    if named:
        routes["search"] = named[0]
    elif len(verb_paths) == 1:
        # exactly one candidate verb route: take it even under a new name.
        routes["search"] = verb_paths[0]
    return routes


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
