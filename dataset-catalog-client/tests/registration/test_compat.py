import logging
from typing import Any

import pytest
from pytest_httpx import HTTPXMock

from catalog_client.client.catalog import AsyncCatalogClient, CatalogClient
from catalog_client.exceptions import AuthenticationError, CompatibilityError
from catalog_client.models.dataset import DatasetRequest
from catalog_client.registration.compat import acheck_compatibility, check_compatibility

BASE = "http://test.local"
TOKEN = "test-token"
SPEC_URL = f"{BASE}/api/v1/meta/openapi.json"
INSTALLED = DatasetRequest.model_fields["record_schema_version"].default


def _spec(record_schema_version: dict[str, Any] | None) -> dict[str, Any]:
    properties = {"canonical_id": {"type": "string"}}
    if record_schema_version is not None:
        properties["record_schema_version"] = record_schema_version
    return {
        "openapi": "3.1.0",
        "components": {"schemas": {"DatasetRequest": {"properties": properties}}},
    }


def _check(httpx_mock: HTTPXMock, spec: dict[str, Any]) -> None:
    httpx_mock.add_response(url=SPEC_URL, json=spec)
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        check_compatibility(client)


@pytest.mark.parametrize("server", [INSTALLED, "v1.0.0", "1.6.9"])
def test_server_equal_or_older_passes(httpx_mock: HTTPXMock, server: str) -> None:
    _check(httpx_mock, _spec({"type": "string", "default": server}))


@pytest.mark.parametrize("server", ["v99.0.0", "2.0.0"])
def test_server_newer_raises(httpx_mock: HTTPXMock, server: str) -> None:
    with pytest.raises(CompatibilityError) as exc_info:
        _check(httpx_mock, _spec({"type": "string", "default": server}))
    message = str(exc_info.value)
    assert f"server expects record schema {server}" in message
    assert f"installed catalog-client supports {INSTALLED}" in message
    assert "upgrade catalog-client" in message


@pytest.mark.parametrize("server", ["v1.9.0", "1.8.1"])
def test_server_newer_minor_or_patch_warns_and_passes(
    httpx_mock: HTTPXMock, caplog: pytest.LogCaptureFixture, server: str
) -> None:
    with caplog.at_level(logging.WARNING):
        _check(httpx_mock, _spec({"type": "string", "default": server}))
    assert f"server record schema {server} is newer" in caplog.text


def test_compares_numerically_not_lexically(
    httpx_mock: HTTPXMock, caplog: pytest.LogCaptureFixture
) -> None:
    # v1.10.0 > v1.8.0 even though "1" < "8" as text.
    with caplog.at_level(logging.WARNING):
        _check(httpx_mock, _spec({"type": "string", "default": "v1.10.0"}))
    assert "is newer" in caplog.text


@pytest.mark.parametrize(
    "prop", [None, {"type": "string"}, {"type": "string", "default": "latest"}]
)
def test_missing_or_unparseable_field_warns_and_passes(
    httpx_mock: HTTPXMock, caplog: pytest.LogCaptureFixture, prop: dict[str, Any] | None
) -> None:
    with caplog.at_level(logging.WARNING):
        _check(httpx_mock, _spec(prop))
    assert "skipping compatibility check" in caplog.text


def test_spec_request_sends_auth_header(httpx_mock: HTTPXMock) -> None:
    _check(httpx_mock, _spec({"type": "string", "default": INSTALLED}))
    assert httpx_mock.get_requests()[0].headers["X-catalog-api-token"] == TOKEN


def test_http_errors_map_to_catalog_errors(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=SPEC_URL, status_code=401, json={"detail": "nope"})
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        with pytest.raises(AuthenticationError):
            check_compatibility(client)


async def test_async_server_newer_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=SPEC_URL, json=_spec({"type": "string", "default": "v99.0.0"})
    )
    async with AsyncCatalogClient(base_url=BASE, api_token=TOKEN) as client:
        with pytest.raises(CompatibilityError):
            await acheck_compatibility(client)


async def test_async_server_equal_passes(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=SPEC_URL, json=_spec({"type": "string", "default": INSTALLED})
    )
    async with AsyncCatalogClient(base_url=BASE, api_token=TOKEN) as client:
        await acheck_compatibility(client)
