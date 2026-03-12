from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catalog_client.client.catalog import CatalogClient

_UNSET: object = object()
_catalog_client_var: ContextVar[object] = ContextVar("catalog_client_var", default=_UNSET)


def set_client(client: CatalogClient) -> Token:
    return _catalog_client_var.set(client)


def reset_client(token: Token) -> None:
    _catalog_client_var.reset(token)


def get_client() -> CatalogClient:
    value = _catalog_client_var.get()
    if value is _UNSET:
        raise RuntimeError(
            "No active CatalogClient. Use `with CatalogClient(...) as client:` "
            "before calling fetch methods on models."
        )
    return value  # type: ignore[return-value]
