"""
Dataset API client.
"""
from catalog_client.client.base import BaseClient
from catalog_client.exceptions import raise_for_status
from catalog_client.models import DatasetCreate, DatasetModality, DatasetResponse, DatasetUpdate, PaginatedResponse


class DatasetClient(BaseClient):
    prefix = "datasets"

    def list_(
        self,
        *,
        canonical_id: str | None = None,
        modality: DatasetModality | None = None,
        project: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[DatasetResponse]:
        params: dict = {"skip": skip, "limit": limit}
        if canonical_id is not None:
            params["canonical_id"] = canonical_id
        if modality is not None:
            params["modality"] = modality.value
        if project is not None:
            params["project"] = project
        response = self._http.get(f"{self.prefix}/", params=params)
        raise_for_status(response)
        return PaginatedResponse[DatasetResponse].model_validate(response.json())

    def get(self, dataset_id: str) -> DatasetResponse:
        response = self._http.get(f"{self.prefix}/{dataset_id}")
        raise_for_status(response)
        return DatasetResponse.model_validate(response.json())

    def create(self, dataset: DatasetCreate) -> DatasetResponse:
        response = self._http.post(f"{self.prefix}/", json=dataset.model_dump(mode="json"))
        raise_for_status(response)
        return DatasetResponse.model_validate(response.json())

    def update(self, dataset_id: str, dataset: DatasetUpdate) -> DatasetResponse:
        response = self._http.patch(
            f"{self.prefix}/{dataset_id}",
            json=dataset.model_dump(mode="json", exclude_unset=True),
        )
        raise_for_status(response)
        return DatasetResponse.model_validate(response.json())

    def delete(self, dataset_id: str) -> None:
        response = self._http.delete(f"{self.prefix}/{dataset_id}")
        raise_for_status(response)
