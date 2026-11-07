"""Top-level CatalogClient and AsyncCatalogClient."""

from __future__ import annotations

import httpx

from catalog_client._context import reset_client, set_client
from catalog_client.client.collections_ import AsyncCollectionClient, CollectionClient
from catalog_client.client.datasets import AsyncDatasetClient, DatasetClient
from catalog_client.client.lineages import AsyncLineageClient, LineageClient
from catalog_client.exceptions import LineageResolutionError, NotFoundError
from catalog_client.models.dataset import DatasetModality, DatasetRef, DatasetRequest
from catalog_client.models.lineage import LineageEdgeRequest
from catalog_client.registration.builder import RegistrationBuilder
from catalog_client.registration.plan import (
    RegistrationPlan,
    check_options,
    decide,
    to_dataset_request,
)
from catalog_client.registration.request import RegistrationRequest
from catalog_client.registration.retry import (
    AsyncRetryTransport,
    RetryPolicy,
    RetryTransport,
)

_API_PREFIX = "/api/v1/"


class CatalogClient:
    """Sync client for the Scientific Dataset Catalog API.

    Usage:
        with CatalogClient(base_url="https://catalog.example.com", api_token="...") as client:
            dataset_id = client.register(request)
            datasets = client.datasets.list()
    """

    def __init__(
        self,
        base_url: str,
        api_token: str,
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + _API_PREFIX,
            headers={"X-catalog-api-token": api_token},
            timeout=timeout,
            transport=RetryTransport(httpx.HTTPTransport(), retry) if retry else None,
        )
        self.datasets = DatasetClient(self._http)
        self.lineages = LineageClient(self._http)
        self.collections = CollectionClient(self._http)
        self._context_token: object = None

    def plan(
        self,
        request: RegistrationRequest | DatasetRequest,
        update_if_exists: bool = False,
        error_on_duplicate: bool = True,
    ) -> RegistrationPlan:
        """Dry run of register(): decide what it would do using GET requests only."""
        dataset = to_dataset_request(request)
        ref = check_options(dataset, update_if_exists, error_on_duplicate)
        page = self.datasets.list(
            canonical_id=ref.canonical_id,
            version=ref.version,
            project=ref.project,
            limit=10,
        )
        action, dataset_id = decide(
            ref, page.results, update_if_exists, error_on_duplicate
        )

        edges: list[LineageEdgeRequest] = []
        for spec in request.lineage if isinstance(request, RegistrationRequest) else []:
            if spec.source_dataset_id is not None:
                source_id = spec.source_dataset_id
            elif spec.source_ref is not None:
                source_id = self._resolve_ref(spec.source_ref)
            else:
                continue
            edge = LineageEdgeRequest(
                source_dataset_id=source_id,
                destination_dataset_id=dataset_id or "",
                lineage_type=spec.lineage_type,
                metadata=spec.metadata,
            )
            # A dataset that does not exist yet has no edges; skip the lookup.
            if dataset_id is None or not self._edge_exists(edge):
                edges.append(edge)
        return RegistrationPlan(action, dataset_id, edges, dataset)

    def register(
        self,
        request: RegistrationRequest | DatasetRequest,
        update_if_exists: bool = False,
        error_on_duplicate: bool = True,
    ) -> str:
        """Register a dataset and any lineage edges. Returns the dataset_id."""
        plan = self.plan(request, update_if_exists, error_on_duplicate)
        dataset_id = plan.dataset_id
        if dataset_id is None:
            dataset_id = self.datasets.create(plan.request).id
        elif plan.action == "update":
            self.datasets.update(dataset_id, plan.request)
        for edge in plan.lineage_to_create:
            self.lineages.create(
                edge.model_copy(update={"destination_dataset_id": dataset_id})
            )
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


class AsyncCatalogClient:
    """Async client for the Scientific Dataset Catalog API.

    Usage:
        async with AsyncCatalogClient(base_url="https://catalog.example.com", api_token="...") as client:
            dataset_id = await client.register(request)
            datasets = await client.datasets.list()
    """

    def __init__(
        self,
        base_url: str,
        api_token: str,
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + _API_PREFIX,
            headers={"X-catalog-api-token": api_token},
            timeout=timeout,
            transport=(
                AsyncRetryTransport(httpx.AsyncHTTPTransport(), retry)
                if retry
                else None
            ),
        )
        self.datasets = AsyncDatasetClient(self._http)
        self.lineages = AsyncLineageClient(self._http)
        self.collections = AsyncCollectionClient(self._http)

    async def plan(
        self,
        request: RegistrationRequest | DatasetRequest,
        update_if_exists: bool = False,
        error_on_duplicate: bool = True,
    ) -> RegistrationPlan:
        """Dry run of register(): decide what it would do using GET requests only."""
        dataset = to_dataset_request(request)
        ref = check_options(dataset, update_if_exists, error_on_duplicate)
        page = await self.datasets.list(
            canonical_id=ref.canonical_id,
            version=ref.version,
            project=ref.project,
            limit=10,
        )
        action, dataset_id = decide(
            ref, page.results, update_if_exists, error_on_duplicate
        )

        edges: list[LineageEdgeRequest] = []
        for spec in request.lineage if isinstance(request, RegistrationRequest) else []:
            if spec.source_dataset_id is not None:
                source_id = spec.source_dataset_id
            elif spec.source_ref is not None:
                source_id = await self._resolve_ref(spec.source_ref)
            else:
                continue
            edge = LineageEdgeRequest(
                source_dataset_id=source_id,
                destination_dataset_id=dataset_id or "",
                lineage_type=spec.lineage_type,
                metadata=spec.metadata,
            )
            # A dataset that does not exist yet has no edges; skip the lookup.
            if dataset_id is None or not await self._edge_exists(edge):
                edges.append(edge)
        return RegistrationPlan(action, dataset_id, edges, dataset)

    async def register(
        self,
        request: RegistrationRequest | DatasetRequest,
        update_if_exists: bool = False,
        error_on_duplicate: bool = True,
    ) -> str:
        """Register a dataset and any lineage edges. Returns the dataset_id."""
        plan = await self.plan(request, update_if_exists, error_on_duplicate)
        dataset_id = plan.dataset_id
        if dataset_id is None:
            dataset_id = (await self.datasets.create(plan.request)).id
        elif plan.action == "update":
            await self.datasets.update(dataset_id, plan.request)
        for edge in plan.lineage_to_create:
            await self.lineages.create(
                edge.model_copy(update={"destination_dataset_id": dataset_id})
            )
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
