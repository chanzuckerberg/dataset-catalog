"""Route self-healing tests for the plugin's stdlib REST fallback client.

The bundled ``plugins/catalog/scripts/_catalog.py`` starts from the dataset
routes known at authoring time and, on a 404/405, re-resolves the current
routes from the live OpenAPI spec and retries — so an API endpoint move
degrades to one extra round-trip instead of a broken script. These tests pin
that behavior with a faked ``urllib`` transport (no network).
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "plugins" / "catalog" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from _catalog import (  # noqa: E402
    CatalogError,
    _dataset_routes_from_spec,
    _RestClient,
)

RENAMED_SPEC: dict = {
    "paths": {
        "/api/v2/datasets/": {"get": {}},
        "/api/v2/datasets/find/": {"get": {}},  # search route under a new name
        "/api/v2/datasets/{dataset_id}": {"get": {}},
        "/api/v2/datasets/{dataset_id}/history": {"get": {}},
        "/api/v2/collections/": {"get": {}},
        "/api/v2/lineage/": {"get": {}},
    }
}


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(routes: dict, calls: list, spec: dict | None = None):
    """Return an ``urlopen`` stand-in serving ``routes`` and optionally a spec."""

    def fake(request, timeout=None):
        path = urllib.parse.urlparse(request.full_url).path
        calls.append(path)
        if spec is not None and path == "/api/meta/openapi.json":
            return _FakeResponse(json.dumps(spec).encode())
        if path in routes:
            return _FakeResponse(json.dumps(routes[path]).encode())
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", {}, io.BytesIO(b"")
        )

    return fake


def test_routes_from_spec_classifies_structurally():
    """A renamed search route is still found: classification is by shape."""
    assert _dataset_routes_from_spec(RENAMED_SPEC) == {
        "search": "/api/v2/datasets/find/",
        "list": "/api/v2/datasets/",
        "get": "/api/v2/datasets/{dataset_id}",
    }


def test_default_routes_used_without_spec_fetch(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen(
            {"/api/datasets/search/": {"total": 1, "results": [{"id": "a"}]}}, calls
        ),
    )
    client = _RestClient("https://x", "t")
    assert client.datasets.search(q="liver").total == 1
    assert calls == ["/api/datasets/search/"]
    assert not client._rediscovered


def test_moved_route_rediscovers_once_and_heals_siblings(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen(
            {
                "/api/v2/datasets/find/": {"total": 2, "results": []},
                "/api/v2/datasets/": {"total": 5, "results": []},
            },
            calls,
            spec=RENAMED_SPEC,
        ),
    )
    client = _RestClient("https://x", "t")
    assert client.datasets.search(q="liver").total == 2
    assert calls == [
        "/api/datasets/search/",  # stale default 404s
        "/api/meta/openapi.json",  # one spec fetch
        "/api/v2/datasets/find/",  # retried on the discovered route
    ]
    # the sibling route was healed by the same spec fetch: no 404, no re-fetch
    assert client.datasets.list().total == 5
    assert calls[3:] == ["/api/v2/datasets/"]


def test_missing_id_is_not_mistaken_for_a_moved_route(monkeypatch):
    """A 404 on the detail route re-checks the spec once, then propagates."""
    unchanged_spec = {
        "paths": {
            "/api/datasets/": {"get": {}},
            "/api/datasets/search/": {"get": {}},
            "/api/datasets/{dataset_id}": {"get": {}},
        }
    }
    calls: list = []
    monkeypatch.setattr(
        "urllib.request.urlopen", _fake_urlopen({}, calls, spec=unchanged_spec)
    )
    client = _RestClient("https://x", "t")
    with pytest.raises(CatalogError) as excinfo:
        client.datasets.get("deadbeef")
    assert getattr(excinfo.value, "status", None) == 404
    # route unchanged after rediscovery -> no pointless retry of the same URL
    assert calls == ["/api/datasets/deadbeef", "/api/meta/openapi.json"]

    calls.clear()
    with pytest.raises(CatalogError):
        client.datasets.get("cafef00d")
    # spec is consulted at most once per client
    assert calls == ["/api/datasets/cafef00d"]


def test_sso_html_spec_does_not_crash_rediscovery(monkeypatch):
    calls: list = []

    def urlopen_html(request, timeout=None):
        path = urllib.parse.urlparse(request.full_url).path
        calls.append(path)
        if "openapi" in path:
            return _FakeResponse(b"<html>login</html>")
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", {}, io.BytesIO(b"")
        )

    monkeypatch.setattr("urllib.request.urlopen", urlopen_html)
    client = _RestClient("https://x", "t")
    with pytest.raises(CatalogError):
        client.datasets.search(q="x")
