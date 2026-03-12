"""Sync and async base client wrappers over httpx transports."""
from __future__ import annotations

import httpx

from catalog_client.exceptions import CatalogConnectionError, raise_for_status


class _SyncBase:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def _get(self, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._http.get(path, **kwargs)
        except httpx.TransportError as exc:
            raise CatalogConnectionError(str(exc)) from exc
        raise_for_status(response)
        return response

    def _post(self, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._http.post(path, **kwargs)
        except httpx.TransportError as exc:
            raise CatalogConnectionError(str(exc)) from exc
        raise_for_status(response)
        return response

    def _patch(self, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._http.patch(path, **kwargs)
        except httpx.TransportError as exc:
            raise CatalogConnectionError(str(exc)) from exc
        raise_for_status(response)
        return response

    def _delete(self, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._http.delete(path, **kwargs)
        except httpx.TransportError as exc:
            raise CatalogConnectionError(str(exc)) from exc
        raise_for_status(response)
        return response

    def _put(self, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._http.put(path, **kwargs)
        except httpx.TransportError as exc:
            raise CatalogConnectionError(str(exc)) from exc
        raise_for_status(response)
        return response


class _AsyncBase:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def __aenter__(self):
        await self._http.__aenter__()
        return self

    async def __aexit__(self, *args):
        await self._http.__aexit__(*args)

    async def _get(self, path: str, **kwargs) -> httpx.Response:
        try:
            response = await self._http.get(path, **kwargs)
        except httpx.TransportError as exc:
            raise CatalogConnectionError(str(exc)) from exc
        raise_for_status(response)
        return response

    async def _post(self, path: str, **kwargs) -> httpx.Response:
        try:
            response = await self._http.post(path, **kwargs)
        except httpx.TransportError as exc:
            raise CatalogConnectionError(str(exc)) from exc
        raise_for_status(response)
        return response

    async def _patch(self, path: str, **kwargs) -> httpx.Response:
        try:
            response = await self._http.patch(path, **kwargs)
        except httpx.TransportError as exc:
            raise CatalogConnectionError(str(exc)) from exc
        raise_for_status(response)
        return response

    async def _delete(self, path: str, **kwargs) -> httpx.Response:
        try:
            response = await self._http.delete(path, **kwargs)
        except httpx.TransportError as exc:
            raise CatalogConnectionError(str(exc)) from exc
        raise_for_status(response)
        return response

    async def _put(self, path: str, **kwargs) -> httpx.Response:
        try:
            response = await self._http.put(path, **kwargs)
        except httpx.TransportError as exc:
            raise CatalogConnectionError(str(exc)) from exc
        raise_for_status(response)
        return response
