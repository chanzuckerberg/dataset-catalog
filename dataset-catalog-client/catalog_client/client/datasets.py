"""Dataset sub-client (sync and async)."""

from __future__ import annotations

import datetime

from catalog_client.client._base import _AsyncBase, _SyncBase
from catalog_client.exceptions import NotFoundError
from catalog_client.models.dataset import (
    AuditLogEventType,
    DatasetAuditLogResponse,
    DatasetModality,
    DatasetRef,
    DatasetRequest,
    DatasetResponse,
    DatasetSearchResponse,
    DatasetSortOption,
    DatasetWithRelationsResponse,
)
from catalog_client.models.pagination import PaginatedResponse

_PREFIX = "datasets"

# Module-level alias so method signatures can reference list[str] without it
# resolving to the class's own `list` method inside the class body.
_FacetList = list[str]


def _build_list_params(
    canonical_id: str | None,
    version: str | None,
    modality: DatasetModality | None,
    project: str | None,
    access_scope: str | None,
    is_latest: bool | None,
    exclude_tombstoned: bool,
    include_lineage: bool,
    include_collections: bool,
    offset: int,
    limit: int,
) -> dict:
    params: dict = {"offset": offset, "limit": limit}
    if canonical_id is not None:
        params["canonical_id"] = canonical_id
    if version is not None:
        params["version"] = version
    if modality is not None:
        params["modality"] = modality.value
    if project is not None:
        params["project"] = project
    if access_scope is not None:
        params["access_scope"] = access_scope
    if is_latest is not None:
        params["is_latest"] = is_latest
    if not exclude_tombstoned:
        params["exclude_tombstoned"] = False
    if include_lineage:
        params["include_lineage"] = True
    if include_collections:
        params["include_collections"] = True
    return params


def _build_search_params(
    q: str | None,
    modality: DatasetModality | None,
    project: str | None,
    is_latest: bool | None,
    access_scope: str | None,
    organism: str | None,
    tissue: str | None,
    sub_modality: str | None,
    assay: str | None,
    disease: str | None,
    development_stage: str | None,
    facets: list[str] | None,
    sort: DatasetSortOption,
    offset: int,
    limit: int,
) -> dict:
    params: dict = {"sort": sort.value, "offset": offset, "limit": limit}
    optional = {
        "q": q,
        "project": project,
        "access_scope": access_scope,
        "organism": organism,
        "tissue": tissue,
        "sub_modality": sub_modality,
        "assay": assay,
        "disease": disease,
        "development_stage": development_stage,
    }
    for key, value in optional.items():
        if value is not None:
            params[key] = value
    if modality is not None:
        params["modality"] = modality.value
    if is_latest is not None:
        params["is_latest"] = is_latest
    if facets:
        params["facets"] = facets
    return params


def _build_history_params(
    actor: str | None,
    event_type: AuditLogEventType | None,
    start_time: datetime.datetime | None,
    end_time: datetime.datetime | None,
    skip: int,
    limit: int,
) -> dict:
    params: dict = {"skip": skip, "limit": limit}
    if actor is not None:
        params["actor"] = actor
    if event_type is not None:
        params["event_type"] = event_type.value
    if start_time is not None:
        params["start_time"] = start_time.isoformat()
    if end_time is not None:
        params["end_time"] = end_time.isoformat()
    return params


class DatasetClient(_SyncBase):
    def list(
        self,
        *,
        canonical_id: str | None = None,
        version: str | None = None,
        modality: DatasetModality | None = None,
        project: str | None = None,
        access_scope: str | None = None,
        is_latest: bool | None = None,
        exclude_tombstoned: bool = True,
        include_lineage: bool = False,
        include_collections: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[DatasetWithRelationsResponse]:
        params = _build_list_params(
            canonical_id,
            version,
            modality,
            project,
            access_scope,
            is_latest,
            exclude_tombstoned,
            include_lineage,
            include_collections,
            offset,
            limit,
        )
        response = self._get(f"{_PREFIX}/", params=params)
        return PaginatedResponse[DatasetWithRelationsResponse].model_validate(
            response.json()
        )

    def search(
        self,
        *,
        q: str | None = None,
        modality: DatasetModality | None = None,
        project: str | None = None,
        is_latest: bool | None = None,
        access_scope: str | None = None,
        organism: str | None = None,
        tissue: str | None = None,
        sub_modality: str | None = None,
        assay: str | None = None,
        disease: str | None = None,
        development_stage: str | None = None,
        facets: _FacetList | None = None,
        sort: DatasetSortOption = DatasetSortOption.relevance,
        offset: int = 0,
        limit: int = 10,
    ) -> DatasetSearchResponse:
        params = _build_search_params(
            q,
            modality,
            project,
            is_latest,
            access_scope,
            organism,
            tissue,
            sub_modality,
            assay,
            disease,
            development_stage,
            facets,
            sort,
            offset,
            limit,
        )
        response = self._get(f"{_PREFIX}/search/", params=params)
        return DatasetSearchResponse.model_validate(response.json())

    def history(
        self,
        dataset_id: str,
        *,
        actor: str | None = None,
        event_type: AuditLogEventType | None = None,
        start_time: datetime.datetime | None = None,
        end_time: datetime.datetime | None = None,
        skip: int = 0,
        limit: int = 10,
    ) -> PaginatedResponse[DatasetAuditLogResponse]:
        params = _build_history_params(
            actor, event_type, start_time, end_time, skip, limit
        )
        response = self._get(f"{_PREFIX}/{dataset_id}/history", params=params)
        return PaginatedResponse[DatasetAuditLogResponse].model_validate(
            response.json()
        )

    def _resolve(self, ref: DatasetRef) -> str:
        response = self.list(
            canonical_id=ref.canonical_id,
            project=ref.project,
            version=ref.version,
            limit=10,
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
        exclude_tombstoned: bool = True,
        include_lineage: bool = False,
        include_collections: bool = False,
    ) -> DatasetWithRelationsResponse:
        dataset_id = ref if isinstance(ref, str) else self._resolve(ref)
        params: dict = {}
        if not exclude_tombstoned:
            params["exclude_tombstoned"] = False
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
        access_scope: str | None = None,
        is_latest: bool | None = None,
        exclude_tombstoned: bool = True,
        include_lineage: bool = False,
        include_collections: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[DatasetWithRelationsResponse]:
        params = _build_list_params(
            canonical_id,
            version,
            modality,
            project,
            access_scope,
            is_latest,
            exclude_tombstoned,
            include_lineage,
            include_collections,
            offset,
            limit,
        )
        response = await self._get(f"{_PREFIX}/", params=params)
        return PaginatedResponse[DatasetWithRelationsResponse].model_validate(
            response.json()
        )

    async def search(
        self,
        *,
        q: str | None = None,
        modality: DatasetModality | None = None,
        project: str | None = None,
        is_latest: bool | None = None,
        access_scope: str | None = None,
        organism: str | None = None,
        tissue: str | None = None,
        sub_modality: str | None = None,
        assay: str | None = None,
        disease: str | None = None,
        development_stage: str | None = None,
        facets: _FacetList | None = None,
        sort: DatasetSortOption = DatasetSortOption.relevance,
        offset: int = 0,
        limit: int = 10,
    ) -> DatasetSearchResponse:
        params = _build_search_params(
            q,
            modality,
            project,
            is_latest,
            access_scope,
            organism,
            tissue,
            sub_modality,
            assay,
            disease,
            development_stage,
            facets,
            sort,
            offset,
            limit,
        )
        response = await self._get(f"{_PREFIX}/search/", params=params)
        return DatasetSearchResponse.model_validate(response.json())

    async def history(
        self,
        dataset_id: str,
        *,
        actor: str | None = None,
        event_type: AuditLogEventType | None = None,
        start_time: datetime.datetime | None = None,
        end_time: datetime.datetime | None = None,
        skip: int = 0,
        limit: int = 10,
    ) -> PaginatedResponse[DatasetAuditLogResponse]:
        params = _build_history_params(
            actor, event_type, start_time, end_time, skip, limit
        )
        response = await self._get(f"{_PREFIX}/{dataset_id}/history", params=params)
        return PaginatedResponse[DatasetAuditLogResponse].model_validate(
            response.json()
        )

    async def _resolve(self, ref: DatasetRef) -> str:
        results = await self.list(
            canonical_id=ref.canonical_id,
            project=ref.project,
            version=ref.version,
            limit=10,
        )
        matches = results.results
        if len(matches) == 0:
            raise NotFoundError(404, f"No dataset found for {ref}")
        if len(matches) > 1:
            raise NotFoundError(404, f"Multiple datasets found for {ref}")
        return matches[0].id

    async def get(
        self,
        ref: str | DatasetRef,
        *,
        exclude_tombstoned: bool = True,
        include_lineage: bool = False,
        include_collections: bool = False,
    ) -> DatasetWithRelationsResponse:
        dataset_id = ref if isinstance(ref, str) else await self._resolve(ref)
        params: dict = {}
        if not exclude_tombstoned:
            params["exclude_tombstoned"] = False
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
