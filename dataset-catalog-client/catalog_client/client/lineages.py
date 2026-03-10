"""
Lineage API client.
"""
from catalog_client.client.base import BaseClient
from catalog_client.exceptions import raise_for_status
from catalog_client.models import DatasetResponse, LineageEdgeCreate, LineageEdgeResponse, LineageType, PaginatedResponse


class LineageClient(BaseClient):
    prefix = "lineage"

    def list_(
        self,
        *,
        source_dataset_id: str | None = None,
        destination_dataset_id: str | None = None,
        lineage_type: LineageType | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> PaginatedResponse[LineageEdgeResponse]:
        params: dict = {"skip": skip, "limit": limit}
        if source_dataset_id is not None:
            params["source_dataset_id"] = source_dataset_id
        if destination_dataset_id is not None:
            params["destination_dataset_id"] = destination_dataset_id
        if lineage_type is not None:
            params["lineage_type"] = lineage_type.value
        response = self._http.get(f"{self.prefix}/", params=params)
        raise_for_status(response)
        return PaginatedResponse[LineageEdgeResponse].model_validate(response.json())

    def get(self, edge_id: str) -> LineageEdgeResponse:
        response = self._http.get(f"{self.prefix}/{edge_id}")
        raise_for_status(response)
        return LineageEdgeResponse.model_validate(response.json())

    def create(self, edge: LineageEdgeCreate) -> LineageEdgeResponse:
        response = self._http.post(f"{self.prefix}/", json=edge.model_dump(mode="json"))
        raise_for_status(response)
        return LineageEdgeResponse.model_validate(response.json())

    def delete(self, edge_id: str) -> None:
        response = self._http.delete(f"{self.prefix}/{edge_id}")
        raise_for_status(response)

    def expand(self, edges: list[LineageEdgeResponse]) -> list[LineageEdgeResponse]:
        """Resolve source_dataset and destination_dataset for each edge.
        Fetches each unique dataset once."""
        dataset_ids = (
            {e.source_dataset_id for e in edges} | {e.destination_dataset_id for e in edges}
        )
        datasets: dict[str, DatasetResponse] = {}
        for dataset_id in dataset_ids:
            response = self._http.get(f"datasets/{dataset_id}")
            raise_for_status(response)
            datasets[dataset_id] = DatasetResponse.model_validate(response.json())

        return [
            edge.model_copy(update={
                "source_dataset": datasets.get(edge.source_dataset_id),
                "destination_dataset": datasets.get(edge.destination_dataset_id),
            })
            for edge in edges
        ]
