"""Collection sub-client (sync and async)."""

from __future__ import annotations

from catalog_client.client._base import _AsyncBase, _SyncBase
from catalog_client.models.collection import (
    ChildCollectionEntryResponse,
    CollectionRequest,
    CollectionResponse,
    DatasetEntryResponse,
)
from catalog_client.models.pagination import PaginatedResponse

_PREFIX = "collections"


def _parse_entry(
    raw: dict,
) -> DatasetEntryResponse | ChildCollectionEntryResponse:
    if raw.get("entry_type") == "dataset":
        return DatasetEntryResponse.model_validate(raw)
    return ChildCollectionEntryResponse.model_validate(raw)


class CollectionClient(_SyncBase):
    def list(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        canonical_id: str | None = None,
        version: str | None = None,
    ) -> PaginatedResponse[CollectionResponse]:
        params: dict = {"offset": offset, "limit": limit}
        if canonical_id is not None:
            params["canonical_id"] = canonical_id
        if version is not None:
            params["version"] = version
        response = self._get(f"{_PREFIX}/", params=params)
        return PaginatedResponse[CollectionResponse].model_validate(response.json())

    def get(self, collection_id: str) -> CollectionResponse:
        response = self._get(f"{_PREFIX}/{collection_id}")
        return CollectionResponse.model_validate(response.json())

    def create(self, collection: CollectionRequest) -> CollectionResponse:
        response = self._post(f"{_PREFIX}/", json=collection.model_dump(mode="json"))
        return CollectionResponse.model_validate(response.json())

    def update(
        self, collection_id: str, collection: CollectionRequest
    ) -> CollectionResponse:
        response = self._patch(
            f"{_PREFIX}/{collection_id}",
            json=collection.model_dump(mode="json", exclude_unset=True),
        )
        return CollectionResponse.model_validate(response.json())

    def delete(self, collection_id: str) -> None:
        self._delete(f"{_PREFIX}/{collection_id}")

    def add_dataset(self, collection_id: str, dataset_id: str) -> CollectionResponse:
        response = self._put(f"{_PREFIX}/{collection_id}/datasets/{dataset_id}")
        return CollectionResponse.model_validate(response.json())

    def remove_dataset(self, collection_id: str, dataset_id: str) -> CollectionResponse:
        response = self._delete(f"{_PREFIX}/{collection_id}/datasets/{dataset_id}")
        return CollectionResponse.model_validate(response.json())

    def add_collection(
        self, collection_id: str, child_collection_id: str
    ) -> CollectionResponse:
        response = self._put(
            f"{_PREFIX}/{collection_id}/collections/{child_collection_id}"
        )
        return CollectionResponse.model_validate(response.json())

    def remove_collection(
        self, collection_id: str, child_collection_id: str
    ) -> CollectionResponse:
        response = self._delete(
            f"{_PREFIX}/{collection_id}/collections/{child_collection_id}"
        )
        return CollectionResponse.model_validate(response.json())

    def list_entries(
        self,
        collection_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[DatasetEntryResponse | ChildCollectionEntryResponse]:
        """Fetch one page of a collection's entries (datasets and child collections).

        Returns the raw mixed response. Callers that need only datasets should
        filter results by ``entry_type == "dataset"``.
        """
        response = self._get(
            f"{_PREFIX}/{collection_id}/entries",
            params={"offset": offset, "limit": min(limit, 100)},
        )
        raw = response.json()
        entries = [_parse_entry(item) for item in raw.get("results", [])]
        return PaginatedResponse[DatasetEntryResponse | ChildCollectionEntryResponse](
            total=raw.get("total", 0),
            limit=raw.get("limit", limit),
            offset=raw.get("offset", offset),
            results=entries,
        )


class AsyncCollectionClient(_AsyncBase):
    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        canonical_id: str | None = None,
        version: str | None = None,
    ) -> PaginatedResponse[CollectionResponse]:
        params: dict = {"offset": offset, "limit": limit}
        if canonical_id is not None:
            params["canonical_id"] = canonical_id
        if version is not None:
            params["version"] = version
        response = await self._get(f"{_PREFIX}/", params=params)
        return PaginatedResponse[CollectionResponse].model_validate(response.json())

    async def get(self, collection_id: str) -> CollectionResponse:
        response = await self._get(f"{_PREFIX}/{collection_id}")
        return CollectionResponse.model_validate(response.json())

    async def create(self, collection: CollectionRequest) -> CollectionResponse:
        response = await self._post(
            f"{_PREFIX}/", json=collection.model_dump(mode="json")
        )
        return CollectionResponse.model_validate(response.json())

    async def update(
        self, collection_id: str, collection: CollectionRequest
    ) -> CollectionResponse:
        response = await self._patch(
            f"{_PREFIX}/{collection_id}",
            json=collection.model_dump(mode="json", exclude_unset=True),
        )
        return CollectionResponse.model_validate(response.json())

    async def delete(self, collection_id: str) -> None:
        await self._delete(f"{_PREFIX}/{collection_id}")

    async def add_dataset(
        self, collection_id: str, dataset_id: str
    ) -> CollectionResponse:
        response = await self._put(f"{_PREFIX}/{collection_id}/datasets/{dataset_id}")
        return CollectionResponse.model_validate(response.json())

    async def remove_dataset(
        self, collection_id: str, dataset_id: str
    ) -> CollectionResponse:
        response = await self._delete(
            f"{_PREFIX}/{collection_id}/datasets/{dataset_id}"
        )
        return CollectionResponse.model_validate(response.json())

    async def list_entries(
        self,
        collection_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[DatasetEntryResponse | ChildCollectionEntryResponse]:
        """Fetch one page of a collection's entries (datasets and child collections).

        Returns the raw mixed response. Callers that need only datasets should
        filter results by ``entry_type == "dataset"``.
        """
        response = await self._get(
            f"{_PREFIX}/{collection_id}/entries",
            params={"offset": offset, "limit": min(limit, 100)},
        )
        raw = response.json()
        entries = [_parse_entry(item) for item in raw.get("results", [])]
        return PaginatedResponse[DatasetEntryResponse | ChildCollectionEntryResponse](
            total=raw.get("total", 0),
            limit=raw.get("limit", limit),
            offset=raw.get("offset", offset),
            results=entries,
        )
