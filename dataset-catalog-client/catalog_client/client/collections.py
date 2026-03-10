"""
Collections API client.
"""
from catalog_client.client.base import BaseClient
from catalog_client.exceptions import raise_for_status
from catalog_client.models import CollectionCreate, CollectionResponse, CollectionUpdate, PaginatedResponse


class CollectionClient(BaseClient):
    prefix = "collections"

    def list_(self, *, skip: int = 0, limit: int = 100) -> PaginatedResponse[CollectionResponse]:
        response = self._http.get(f"{self.prefix}/", params={"skip": skip, "limit": limit})
        raise_for_status(response)
        return PaginatedResponse[CollectionResponse].model_validate(response.json())

    def get(self, collection_id: str) -> CollectionResponse:
        response = self._http.get(f"{self.prefix}/{collection_id}")
        raise_for_status(response)
        return CollectionResponse.model_validate(response.json())

    def create(self, collection: CollectionCreate) -> CollectionResponse:
        response = self._http.post(f"{self.prefix}/", json=collection.model_dump(mode="json"))
        raise_for_status(response)
        return CollectionResponse.model_validate(response.json())

    def update(self, collection_id: str, collection: CollectionUpdate) -> CollectionResponse:
        response = self._http.patch(
            f"{self.prefix}/{collection_id}",
            json=collection.model_dump(mode="json", exclude_unset=True),
        )
        raise_for_status(response)
        return CollectionResponse.model_validate(response.json())

    def delete(self, collection_id: str) -> None:
        response = self._http.delete(f"{self.prefix}/{collection_id}")
        raise_for_status(response)

    def add_dataset(self, collection_id: str, dataset_id: str) -> CollectionResponse:
        response = self._http.put(f"{self.prefix}/{collection_id}/datasets/{dataset_id}")
        raise_for_status(response)
        return CollectionResponse.model_validate(response.json())

    def remove_dataset(self, collection_id: str, dataset_id: str) -> CollectionResponse:
        response = self._http.delete(f"{self.prefix}/{collection_id}/datasets/{dataset_id}")
        raise_for_status(response)
        return CollectionResponse.model_validate(response.json())
