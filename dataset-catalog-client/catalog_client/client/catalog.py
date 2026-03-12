"""Top-level CatalogClient and AsyncCatalogClient."""
from __future__ import annotations

import httpx

from catalog_client._context import reset_client, set_client
from catalog_client.client.collections import AsyncCollectionClient, CollectionClient
from catalog_client.client.datasets import AsyncDatasetClient, DatasetClient
from catalog_client.client.lineages import AsyncLineageClient, LineageClient
from catalog_client.exceptions import LineageResolutionError, NotFoundError
from catalog_client.models.dataset import DatasetCreate, DatasetModality, DatasetRef
from catalog_client.models.lineage import LineageEdgeCreate
from catalog_client.registration.builder import RegistrationBuilder
from catalog_client.registration.request import RegistrationRequest


class CatalogClient:
    """Sync client for the Scientific Dataset Catalog API.

    Usage:
        with CatalogClient(base_url="https://catalog.example.com", api_token="...") as client:
            dataset_id = client.register(request)
            datasets = client.datasets.list()
    """

    def __init__(self, base_url: str, api_token: str, timeout: float = 30.0) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/",
            headers={"X-catalog-api-token": api_token},
            timeout=timeout,
        )
        self.datasets = DatasetClient(self._http)
        self.lineages = LineageClient(self._http)
        self.collections = CollectionClient(self._http)
        self._context_token: object = None

    def register(self, request: RegistrationRequest) -> str:
        """Register a new dataset and any lineage edges. Returns the new dataset_id."""
        dataset = DatasetCreate(
            canonical_id=request.canonical_id,
            name=request.name,
            version=request.version,
            project=request.project,
            modality=request.modality,
            locations=request.locations,
            governance=request.governance,
            metadata=request.metadata,
            description=request.description,
            dataset_type=request.dataset_type,
            data_quality=request.data_quality,
            is_latest=request.is_latest,
        )
        response = self.datasets.create(dataset)
        dataset_id = response.id

        for spec in request.lineage:
            if spec.source_dataset_id is not None:
                source_id = spec.source_dataset_id
            elif spec.source_ref is not None:
                source_id = self._resolve_ref(spec.source_ref)
            else:
                continue

            self.lineages.create(LineageEdgeCreate(
                source_dataset_id=source_id,
                destination_dataset_id=dataset_id,
                lineage_type=spec.lineage_type,
            ))

        return dataset_id

    def _resolve_ref(self, ref: DatasetRef) -> str:
        try:
            return self.datasets._resolve(ref)
        except NotFoundError as exc:
            raise LineageResolutionError(ref=ref, reason=str(exc)) from exc

    def new_registration(
        self,
        canonical_id: str,
        version: str,
        project: str,
        modality: DatasetModality,
    ) -> RegistrationBuilder:
        """Return a fluent builder bound to this client."""
        return RegistrationBuilder(
            canonical_id=canonical_id,
            version=version,
            project=project,
            modality=modality,
            client=self,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> CatalogClient:
        self._context_token = set_client(self)
        return self

    def __exit__(self, *args: object) -> None:
        if self._context_token is not None:
            reset_client(self._context_token)  # type: ignore[arg-type]
            self._context_token = None
        self.close()


class AsyncCatalogClient:
    """Async client for the Scientific Dataset Catalog API.

    Usage:
        async with AsyncCatalogClient(base_url="https://catalog.example.com", api_token="...") as client:
            dataset_id = await client.register(request)
            datasets = await client.datasets.list()
    """

    def __init__(self, base_url: str, api_token: str, timeout: float = 30.0) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/api/",
            headers={"X-catalog-api-token": api_token},
            timeout=timeout,
        )
        self.datasets = AsyncDatasetClient(self._http)
        self.lineages = AsyncLineageClient(self._http)
        self.collections = AsyncCollectionClient(self._http)

    async def register(self, request: RegistrationRequest) -> str:
        """Register a new dataset and any lineage edges. Returns the new dataset_id."""
        dataset = DatasetCreate(
            canonical_id=request.canonical_id,
            name=request.name,
            version=request.version,
            project=request.project,
            modality=request.modality,
            locations=request.locations,
            governance=request.governance,
            metadata=request.metadata,
            description=request.description,
            dataset_type=request.dataset_type,
            data_quality=request.data_quality,
            is_latest=request.is_latest,
        )
        response = await self.datasets.create(dataset)
        dataset_id = response.id

        for spec in request.lineage:
            if spec.source_dataset_id is not None:
                source_id = spec.source_dataset_id
            elif spec.source_ref is not None:
                source_id = await self._resolve_ref(spec.source_ref)
            else:
                continue

            await self.lineages.create(LineageEdgeCreate(
                source_dataset_id=source_id,
                destination_dataset_id=dataset_id,
                lineage_type=spec.lineage_type,
            ))

        return dataset_id

    async def _resolve_ref(self, ref: DatasetRef) -> str:
        try:
            return await self.datasets._resolve(ref)
        except NotFoundError as exc:
            raise LineageResolutionError(ref=ref, reason=str(exc)) from exc

    def new_registration(
        self,
        canonical_id: str,
        version: str,
        project: str,
        modality: DatasetModality,
    ) -> RegistrationBuilder:
        return RegistrationBuilder(
            canonical_id=canonical_id,
            version=version,
            project=project,
            modality=modality,
            client=self,  # type: ignore[arg-type]
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncCatalogClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
