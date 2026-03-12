"""Lineage sub-client (sync and async)."""
from __future__ import annotations

from catalog_client.client._base import _AsyncBase, _SyncBase
from catalog_client.models.lineage import LineageEdgeCreate, LineageEdgeResponse, LineageType
from catalog_client.models.pagination import PaginatedResponse

_PREFIX = "lineage"


class LineageClient(_SyncBase):
    def list(
        self,
        *,
        source_dataset_id: str | None = None,
        destination_dataset_id: str | None = None,
        lineage_type: LineageType | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[LineageEdgeResponse]:
        params: dict = {"offset": offset, "limit": limit}
        if source_dataset_id is not None:
            params["source_dataset_id"] = source_dataset_id
        if destination_dataset_id is not None:
            params["destination_dataset_id"] = destination_dataset_id
        if lineage_type is not None:
            params["lineage_type"] = lineage_type.value
        response = self._get(f"{_PREFIX}/", params=params)
        return PaginatedResponse[LineageEdgeResponse].model_validate(response.json())

    def get(self, edge_id: str) -> LineageEdgeResponse:
        response = self._get(f"{_PREFIX}/{edge_id}")
        return LineageEdgeResponse.model_validate(response.json())

    def create(self, edge: LineageEdgeCreate) -> LineageEdgeResponse:
        response = self._post(f"{_PREFIX}/", json=edge.model_dump(mode="json"))
        return LineageEdgeResponse.model_validate(response.json())

    def delete(self, edge_id: str) -> None:
        self._delete(f"{_PREFIX}/{edge_id}")


class AsyncLineageClient(_AsyncBase):
    async def list(
        self,
        *,
        source_dataset_id: str | None = None,
        destination_dataset_id: str | None = None,
        lineage_type: LineageType | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[LineageEdgeResponse]:
        params: dict = {"offset": offset, "limit": limit}
        if source_dataset_id is not None:
            params["source_dataset_id"] = source_dataset_id
        if destination_dataset_id is not None:
            params["destination_dataset_id"] = destination_dataset_id
        if lineage_type is not None:
            params["lineage_type"] = lineage_type.value
        response = await self._get(f"{_PREFIX}/", params=params)
        return PaginatedResponse[LineageEdgeResponse].model_validate(response.json())

    async def get(self, edge_id: str) -> LineageEdgeResponse:
        response = await self._get(f"{_PREFIX}/{edge_id}")
        return LineageEdgeResponse.model_validate(response.json())

    async def create(self, edge: LineageEdgeCreate) -> LineageEdgeResponse:
        response = await self._post(f"{_PREFIX}/", json=edge.model_dump(mode="json"))
        return LineageEdgeResponse.model_validate(response.json())

    async def delete(self, edge_id: str) -> None:
        await self._delete(f"{_PREFIX}/{edge_id}")
