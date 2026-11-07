"""Top-level CatalogClient and AsyncCatalogClient."""

from __future__ import annotations

import httpx

from catalog_client._context import reset_client, set_client
from catalog_client.client.collections_ import AsyncCollectionClient, CollectionClient
from catalog_client.client.datasets import AsyncDatasetClient, DatasetClient
from catalog_client.client.lineages import AsyncLineageClient, LineageClient
from catalog_client.exceptions import (
    CatalogError,
    DuplicateDatasetError,
    LineageResolutionError,
    NotFoundError,
)
from catalog_client.models.dataset import DatasetModality, DatasetRef, DatasetRequest
from catalog_client.models.lineage import LineageEdgeRequest
from catalog_client.registration.builder import RegistrationBuilder
from catalog_client.registration.request import RegistrationRequest

_API_PREFIX = "/api/v1/"


class CatalogClient:
    """Sync client for the Scientific Dataset Catalog API.

    Usage:
        with CatalogClient(base_url="https://catalog.example.com", api_token="...") as client:
            dataset_id = client.register(request)
            datasets = client.datasets.list()
    """

    def __init__(self, base_url: str, api_token: str, timeout: float = 30.0) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + _API_PREFIX,
            headers={"X-catalog-api-token": api_token},
            timeout=timeout,
        )
        self.datasets = DatasetClient(self._http)
        self.lineages = LineageClient(self._http)
        self.collections = CollectionClient(self._http)
        self._context_token: object = None

    def register(
        self,
        request: RegistrationRequest | DatasetRequest,
        update_if_exists: bool = False,
        error_on_duplicate: bool = True,
    ) -> str:
        """Register a dataset and any lineage edges. Returns the dataset_id."""
        if isinstance(request, RegistrationRequest):
            dataset_request = request.to_dataset_request()
        else:
            dataset_request = request
        dataset_id, created = self._create_or_update(
            dataset_request, update_if_exists, error_on_duplicate
        )

        if isinstance(request, RegistrationRequest):
            for spec in request.lineage:
                if spec.source_dataset_id is not None:
                    source_id = spec.source_dataset_id
                elif spec.source_ref is not None:
                    source_id = self._resolve_ref(spec.source_ref)
                else:
                    continue

                edge = LineageEdgeRequest(
                    source_dataset_id=source_id,
                    destination_dataset_id=dataset_id,
                    lineage_type=spec.lineage_type,
                    metadata=spec.metadata,
                )
                # A dataset created just now has no edges yet; skip the lookup.
                if not created and self._edge_exists(edge):
                    continue
                self.lineages.create(edge)

        return dataset_id

    def _resolve_ref(self, ref: DatasetRef) -> str:
        try:
            return self.datasets._resolve(ref)
        except NotFoundError as exc:
            raise LineageResolutionError(ref=ref, reason=str(exc)) from exc

    def _edge_exists(self, edge: LineageEdgeRequest) -> bool:
        page = self.lineages.list(
            source_dataset_id=edge.source_dataset_id,
            destination_dataset_id=edge.destination_dataset_id,
            lineage_type=edge.lineage_type,
            limit=1,
        )
        return bool(page.results)

    def new_registration(
        self,
        canonical_id: str,
        name: str,
        version: str,
        project: str,
        modality: DatasetModality,
    ) -> RegistrationBuilder:
        """Return a fluent builder bound to this client."""
        return RegistrationBuilder(
            canonical_id=canonical_id,
            name=name,
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

    def _create_or_update(
        self, dataset: DatasetRequest, update_if_exists: bool, error_on_duplicate: bool
    ) -> tuple[str, bool]:
        """Create or update a dataset. Returns (dataset_id, created)."""
        # Validate mutually exclusive parameters
        if update_if_exists and error_on_duplicate:
            raise ValueError(
                "update_if_exists and error_on_duplicate cannot both be True"
            )

        if dataset.project is None:
            raise ValueError("project is required to register a dataset")

        dataset_ref = DatasetRef(
            canonical_id=dataset.canonical_id,
            version=dataset.version,
            project=dataset.project,
        )

        # Search for existing datasets with same canonical_id, version, and project
        results = self.datasets.list(
            canonical_id=dataset.canonical_id,
            version=dataset.version,
            project=dataset.project,
            limit=10,  # reasonable limit for duplicates check
        )
        existing_datasets = results.results

        # No existing dataset found - create new one
        if not existing_datasets:
            response = self.datasets.create(dataset)
            return response.id, True

        # Found existing dataset(s) - handle based on parameters
        if error_on_duplicate:
            raise DuplicateDatasetError(dataset_ref)

        if len(existing_datasets) > 1:
            raise CatalogError(
                f"Multiple datasets found ({len(existing_datasets)}) for {dataset_ref!r}"
            )

        if update_if_exists:
            existing_dataset = existing_datasets[0]
            self.datasets.update(existing_dataset.id, dataset)
            return existing_dataset.id, False

        # Default: return existing dataset ID without error
        return existing_datasets[0].id, False


class AsyncCatalogClient:
    """Async client for the Scientific Dataset Catalog API.

    Usage:
        async with AsyncCatalogClient(base_url="https://catalog.example.com", api_token="...") as client:
            dataset_id = await client.register(request)
            datasets = await client.datasets.list()
    """

    def __init__(self, base_url: str, api_token: str, timeout: float = 30.0) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + _API_PREFIX,
            headers={"X-catalog-api-token": api_token},
            timeout=timeout,
        )
        self.datasets = AsyncDatasetClient(self._http)
        self.lineages = AsyncLineageClient(self._http)
        self.collections = AsyncCollectionClient(self._http)

    async def register(
        self,
        request: RegistrationRequest | DatasetRequest,
        update_if_exists: bool = False,
        error_on_duplicate: bool = True,
    ) -> str:
        """Register a dataset and any lineage edges. Returns the dataset_id."""
        if isinstance(request, RegistrationRequest):
            dataset_request = request.to_dataset_request()
        else:
            dataset_request = request
        dataset_id, created = await self._create_or_update(
            dataset_request, update_if_exists, error_on_duplicate
        )

        if isinstance(request, RegistrationRequest):
            for spec in request.lineage:
                if spec.source_dataset_id is not None:
                    source_id = spec.source_dataset_id
                elif spec.source_ref is not None:
                    source_id = await self._resolve_ref(spec.source_ref)
                else:
                    continue

                edge = LineageEdgeRequest(
                    source_dataset_id=source_id,
                    destination_dataset_id=dataset_id,
                    lineage_type=spec.lineage_type,
                    metadata=spec.metadata,
                )
                # A dataset created just now has no edges yet; skip the lookup.
                if not created and await self._edge_exists(edge):
                    continue
                await self.lineages.create(edge)

        return dataset_id

    async def _resolve_ref(self, ref: DatasetRef) -> str:
        try:
            return await self.datasets._resolve(ref)
        except NotFoundError as exc:
            raise LineageResolutionError(ref=ref, reason=str(exc)) from exc

    async def _edge_exists(self, edge: LineageEdgeRequest) -> bool:
        page = await self.lineages.list(
            source_dataset_id=edge.source_dataset_id,
            destination_dataset_id=edge.destination_dataset_id,
            lineage_type=edge.lineage_type,
            limit=1,
        )
        return bool(page.results)

    async def _create_or_update(
        self, dataset: DatasetRequest, update_if_exists: bool, error_on_duplicate: bool
    ) -> tuple[str, bool]:
        """Create or update a dataset. Returns (dataset_id, created)."""
        if update_if_exists and error_on_duplicate:
            raise ValueError(
                "update_if_exists and error_on_duplicate cannot both be True"
            )

        if dataset.project is None:
            raise ValueError("project is required to register a dataset")

        dataset_ref = DatasetRef(
            canonical_id=dataset.canonical_id,
            version=dataset.version,
            project=dataset.project,
        )

        results = await self.datasets.list(
            canonical_id=dataset.canonical_id,
            version=dataset.version,
            project=dataset.project,
            limit=10,
        )
        existing_datasets = results.results

        if not existing_datasets:
            response = await self.datasets.create(dataset)
            return response.id, True

        if error_on_duplicate:
            raise DuplicateDatasetError(dataset_ref)

        if len(existing_datasets) > 1:
            raise CatalogError(
                f"Multiple datasets found ({len(existing_datasets)}) for {dataset_ref!r}"
            )

        if update_if_exists:
            existing_dataset = existing_datasets[0]
            await self.datasets.update(existing_dataset.id, dataset)
            return existing_dataset.id, False

        return existing_datasets[0].id, False

    def new_registration(
        self,
        canonical_id: str,
        name: str,
        version: str,
        project: str,
        modality: DatasetModality,
    ) -> RegistrationBuilder:
        return RegistrationBuilder(
            canonical_id=canonical_id,
            name=name,
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
