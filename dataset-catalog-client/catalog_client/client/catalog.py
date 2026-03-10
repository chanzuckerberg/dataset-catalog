"""
Catalog API client.
"""
import httpx

from catalog_client._context import reset_client, set_client
from catalog_client.client.collections import CollectionClient
from catalog_client.client.datasets import DatasetClient
from catalog_client.client.lineages import LineageClient
from catalog_client.client.tokens import TokenClient


class CatalogClient:
    """
    Client for the MetaHub Catalog API.

    Usage:
        client = CatalogClient(
            base_url="https://your-catalog.example.com",
            api_token="your-token",
        )
        datasets = client.datasets.list_()
        lineages = client.lineages.list_()
    """

    def __init__(self, base_url: str, api_token: str, timeout: float = 30.0) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/",
            headers={"X-catalog-api-token": api_token},
            timeout=timeout,
        )
        self.datasets = DatasetClient(self._http)
        self.collections = CollectionClient(self._http)
        self.lineages = LineageClient(self._http)
        self._context_token: object = None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "CatalogClient":
        self._context_token = set_client(self)
        return self

    def __exit__(self, *args: object) -> None:
        if self._context_token is not None:
            reset_client(self._context_token)  # type: ignore[arg-type]
            self._context_token = None
        self.close()
