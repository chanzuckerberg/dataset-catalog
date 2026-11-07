"""Startup check that the server does not expect a newer record schema than this client writes."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from catalog_client.client._base import _AsyncBase, _SyncBase
from catalog_client.exceptions import CompatibilityError
from catalog_client.models.dataset import DatasetRequest

if TYPE_CHECKING:
    from catalog_client.client.catalog import AsyncCatalogClient, CatalogClient

_logger = logging.getLogger(__name__)

_SPEC_PATH = "meta/openapi.json"
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def _parse(version: str) -> tuple[int, int, int] | None:
    match = _SEMVER.match(version)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def _server_schema_version(spec: Any) -> str | None:
    try:
        prop = spec["components"]["schemas"]["DatasetRequest"]["properties"][
            "record_schema_version"
        ]
    except (KeyError, TypeError):
        return None
    default = prop.get("default") if isinstance(prop, dict) else None
    return default if isinstance(default, str) else None


def _compare(spec: Any) -> None:
    installed = DatasetRequest.model_fields["record_schema_version"].default
    server = _server_schema_version(spec)
    server_semver = _parse(server) if server else None
    if server is None or server_semver is None:
        _logger.warning(
            "server OpenAPI spec does not report a parseable "
            "DatasetRequest.record_schema_version (got %r); skipping compatibility check",
            server,
        )
        return
    installed_semver = _parse(installed)
    if installed_semver is not None and server_semver > installed_semver:
        raise CompatibilityError(
            f"server expects record schema {server}, installed catalog-client "
            f"supports {installed} — upgrade catalog-client"
        )


def check_compatibility(client: CatalogClient) -> None:
    _compare(_SyncBase(client._http)._get(_SPEC_PATH).json())


async def acheck_compatibility(client: AsyncCatalogClient) -> None:
    response = await _AsyncBase(client._http)._get(_SPEC_PATH)
    _compare(response.json())
