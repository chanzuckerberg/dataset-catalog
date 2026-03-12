"""Dataset sub-client (sync and async)."""
from __future__ import annotations

import httpx

from catalog_client.client._base import _AsyncBase, _SyncBase
from catalog_client.exceptions import NotFoundError
from catalog_client.models.dataset import (
    DatasetCreate,
    DatasetModality,
    DatasetRef,
    DatasetResponse,
    DatasetUpdate,
    DatasetWithRelationsResponse,
)
from catalog_client.models.pagination import PaginatedResponse

_PREFIX = "datasets"


def _build_list_params(
    canonical_id: str | None,
    modality: DatasetModality | None,
    project: str | None,
    is_latest: bool | None,
    include_lineage: bool,
    include_collections: bool,
    offset: int,
    limit: int,
) -> dict:
    params: dict = {"offset": offset, "limit": limit}
    if canonical_id is not None:
        params["canonical_id"] = canonical_id
    if modality is not None:
        params["modality"] = modality.value
    if project is not None:
        params["project"] = project
    if is_latest is not None:
        params["is_latest"] = is_latest
    if include_lineage:
        params["include_lineage"] = True
    if include_collections:
        params["include_collections"] = True
    return params


class DatasetClient(_SyncBase):
    def list(
        self,
        *,
        canonical_id: str | None = None,
        modality: DatasetModality | None = None,
        project: str | None = None,
        is_latest: bool | None = None,
        include_lineage: bool = False,
        include_collections: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[DatasetWithRelationsResponse]:
        params = _build_list_params(
            canonical_id, modality, project, is_latest,
            include_lineage, include_collections, offset, limit,
        )
        response = self._get(f"{_PREFIX}/", params=params)
        return PaginatedResponse[DatasetWithRelationsResponse].model_validate(response.json())

    def _resolve(self, ref: DatasetRef) -> str:
        results = self.list(canonical_id=ref.canonical_id, project=ref.project, limit=1000)
        matches = [d for d in results.results if d.version == ref.version]
        if len(matches) == 0:
            raise NotFoundError(404, f"No dataset found for {ref}")
        if len(matches) > 1:
            raise NotFoundError(404, f"Multiple datasets found for {ref}")
        return matches[0].id

    def get(
        self,
        ref: str | DatasetRef,
        *,
        include_lineage: bool = False,
        include_collections: bool = False,
    ) -> DatasetWithRelationsResponse:
        dataset_id = ref if isinstance(ref, str) else self._resolve(ref)
        params: dict = {}
        if include_lineage:
            params["include_lineage"] = True
        if include_collections:
            params["include_collections"] = True
        response = self._get(f"{_PREFIX}/{dataset_id}", params=params)
        return DatasetWithRelationsResponse.model_validate(response.json())

    def create(self, dataset: DatasetCreate) -> DatasetResponse:
        response = self._post(f"{_PREFIX}/", json=dataset.model_dump(mode="json"))
        return DatasetResponse.model_validate(response.json())

    def update(self, ref: str | DatasetRef, dataset: DatasetUpdate) -> DatasetResponse:
        dataset_id = ref if isinstance(ref, str) else self._resolve(ref)
        response = self._patch(
            f"{_PREFIX}/{dataset_id}",
            json=dataset.model_dump(mode="json", exclude_unset=True),
        )
        return DatasetResponse.model_validate(response.json())

    def delete(self, ref: str | DatasetRef) -> None:
        dataset_id = ref if isinstance(ref, str) else self._resolve(ref)
        self._delete(f"{_PREFIX}/{dataset_id}")


class AsyncDatasetClient(_AsyncBase):
    async def list(
        self,
        *,
        canonical_id: str | None = None,
        modality: DatasetModality | None = None,
        project: str | None = None,
        is_latest: bool | None = None,
        include_lineage: bool = False,
        include_collections: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[DatasetWithRelationsResponse]:
        params = _build_list_params(
            canonical_id, modality, project, is_latest,
            include_lineage, include_collections, offset, limit,
        )
        response = await self._get(f"{_PREFIX}/", params=params)
        return PaginatedResponse[DatasetWithRelationsResponse].model_validate(response.json())

    async def _resolve(self, ref: DatasetRef) -> str:
        results = await self.list(canonical_id=ref.canonical_id, project=ref.project, limit=1000)
        matches = [d for d in results.results if d.version == ref.version]
        if len(matches) == 0:
            raise NotFoundError(404, f"No dataset found for {ref}")
        if len(matches) > 1:
            raise NotFoundError(404, f"Multiple datasets found for {ref}")
        return matches[0].id

    async def get(
        self,
        ref: str | DatasetRef,
        *,
        include_lineage: bool = False,
        include_collections: bool = False,
    ) -> DatasetWithRelationsResponse:
        dataset_id = ref if isinstance(ref, str) else await self._resolve(ref)
        params: dict = {}
        if include_lineage:
            params["include_lineage"] = True
        if include_collections:
            params["include_collections"] = True
        response = await self._get(f"{_PREFIX}/{dataset_id}", params=params)
        return DatasetWithRelationsResponse.model_validate(response.json())

    async def create(self, dataset: DatasetCreate) -> DatasetResponse:
        response = await self._post(f"{_PREFIX}/", json=dataset.model_dump(mode="json"))
        return DatasetResponse.model_validate(response.json())

    async def update(self, ref: str | DatasetRef, dataset: DatasetUpdate) -> DatasetResponse:
        dataset_id = ref if isinstance(ref, str) else await self._resolve(ref)
        response = await self._patch(
            f"{_PREFIX}/{dataset_id}",
            json=dataset.model_dump(mode="json", exclude_unset=True),
        )
        return DatasetResponse.model_validate(response.json())

    async def delete(self, ref: str | DatasetRef) -> None:
        dataset_id = ref if isinstance(ref, str) else await self._resolve(ref)
        await self._delete(f"{_PREFIX}/{dataset_id}")
