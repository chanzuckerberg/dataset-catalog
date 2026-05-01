"""Dataset sub-client (sync and async)."""

from __future__ import annotations

from catalog_client.client._base import _AsyncBase, _SyncBase
from catalog_client.exceptions import NotFoundError
from catalog_client.models.dataset import (
    DatasetModality,
    DatasetRef,
    DatasetRequest,
    DatasetResponse,
    DatasetWithRelationsResponse,
)
from catalog_client.models.pagination import PaginatedResponse

_PREFIX = "datasets"


def _build_list_params(
    canonical_id: str | None,
    version: str | None,
    modality: DatasetModality | None,
    project: str | None,
    is_latest: bool,
    include_lineage: bool,
    include_collections: bool,
    exclude_tombstoned: bool,
    offset: int,
    limit: int,
) -> dict:
    params: dict = {
        "offset": offset,
        "limit": limit,
        "include_lineage": include_lineage,
        "include_collections": include_collections,
        "exclude_tombstoned": exclude_tombstoned,
        "is_latest": is_latest,
    }
    if canonical_id is not None:
        params["canonical_id"] = canonical_id
    if version is not None:
        params["version"] = version
    if modality is not None:
        params["modality"] = modality.value
    if project is not None:
        params["project"] = project
    return params


class DatasetClient(_SyncBase):
    def list(
        self,
        *,
        canonical_id: str | None = None,
        version: str | None = None,
        modality: DatasetModality | None = None,
        project: str | None = None,
        is_latest: bool = True,
        include_lineage: bool = False,
        include_collections: bool = False,
        exclude_tombstoned: bool = True,
        offset: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[DatasetWithRelationsResponse]:
        params = _build_list_params(
            canonical_id,
            version,
            modality,
            project,
            is_latest,
            include_lineage,
            include_collections,
            exclude_tombstoned,
            offset,
            limit,
        )
        response = self._get(f"{_PREFIX}/", params=params)
        return PaginatedResponse[DatasetWithRelationsResponse].model_validate(
            response.json()
        )

    def _resolve(self, ref: DatasetRef) -> str:
        response = self.list(
            canonical_id=ref.canonical_id,
            project=ref.project,
            version=ref.version,
            limit=10,
            exclude_tombstoned=False,
        )
        result = response.results
        if len(result) == 0:
            raise NotFoundError(404, f"No dataset found for {ref}")
        if len(result) > 1:
            raise NotFoundError(404, f"Multiple datasets found for {ref}")
        return result[0].id

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

    def create(self, dataset: DatasetRequest) -> DatasetResponse:
        response = self._post(f"{_PREFIX}/", json=dataset.model_dump(mode="json"))
        return DatasetResponse.model_validate(response.json())

    def update(self, ref: str | DatasetRef, dataset: DatasetRequest) -> DatasetResponse:
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
        version: str | None = None,
        modality: DatasetModality | None = None,
        project: str | None = None,
        is_latest: bool = True,
        include_lineage: bool = False,
        include_collections: bool = False,
        exclude_tombstoned: bool = True,
        offset: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[DatasetWithRelationsResponse]:
        params = _build_list_params(
            canonical_id,
            version,
            modality,
            project,
            is_latest,
            include_lineage,
            include_collections,
            exclude_tombstoned,
            offset,
            limit,
        )
        response = await self._get(f"{_PREFIX}/", params=params)
        return PaginatedResponse[DatasetWithRelationsResponse].model_validate(
            response.json()
        )

    async def _resolve(self, ref: DatasetRef) -> str:
        results = await self.list(
            canonical_id=ref.canonical_id, project=ref.project, limit=1000
        )
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

    async def create(self, dataset: DatasetRequest) -> DatasetResponse:
        response = await self._post(f"{_PREFIX}/", json=dataset.model_dump(mode="json"))
        return DatasetResponse.model_validate(response.json())

    async def update(
        self, ref: str | DatasetRef, dataset: DatasetRequest
    ) -> DatasetResponse:
        dataset_id = ref if isinstance(ref, str) else await self._resolve(ref)
        response = await self._patch(
            f"{_PREFIX}/{dataset_id}",
            json=dataset.model_dump(mode="json", exclude_unset=True),
        )
        return DatasetResponse.model_validate(response.json())

    async def delete(self, ref: str | DatasetRef) -> None:
        dataset_id = ref if isinstance(ref, str) else await self._resolve(ref)
        await self._delete(f"{_PREFIX}/{dataset_id}")
