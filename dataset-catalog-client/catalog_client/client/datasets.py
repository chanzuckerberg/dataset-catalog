"""Dataset sub-client (sync and async)."""

from __future__ import annotations

import datetime
from collections.abc import AsyncIterator, Iterator

from catalog_client.client._base import _AsyncBase, _SyncBase
from catalog_client.exceptions import NotFoundError
from catalog_client.models.dataset import (
    AuditLogEventType,
    DatasetAuditLogResponse,
    DatasetListSortOption,
    DatasetModality,
    DatasetRef,
    DatasetRequest,
    DatasetResponse,
    DatasetSearchHit,
    DatasetSearchResponse,
    DatasetSortOption,
    DatasetWithRelationsResponse,
)
from catalog_client.models.pagination import CursorPaginatedResponse, PaginatedResponse

_PREFIX = "datasets"

# `hydrate=True` re-reads every hit from the database, so the server caps the
# page size lower than the 1000 an unhydrated search allows.
_HYDRATED_MAX_LIMIT = 100

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
    sort: DatasetListSortOption | None,
    cursor: str | None,
    offset: int | None,
    limit: int,
    include_total: bool,
) -> dict:
    if cursor is not None and offset is not None:
        raise ValueError(
            "cursor and offset are mutually exclusive; pass only one "
            "(prefer cursor past a few thousand records)"
        )
    params: dict = {"limit": limit}
    if sort is not None:
        params["sort"] = sort.value
    if cursor is not None:
        params["cursor"] = cursor
    elif offset is not None:
        params["offset"] = offset
    if not include_total:
        params["include_total"] = False
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
    cohort: str | None,
    file_format: str | None,
    storage_platform: str | None,
    facets: list[str] | None,
    fields: list[str] | None,
    sort: DatasetSortOption | None,
    cursor: str | None,
    limit: int,
    hydrate: bool,
) -> dict:
    if hydrate and limit > _HYDRATED_MAX_LIMIT:
        raise ValueError(
            f"limit must be <= {_HYDRATED_MAX_LIMIT} when hydrate=True, got {limit}"
        )
    params: dict = {"limit": limit}
    if sort is not None:
        params["sort"] = sort.value
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
        "cohort": cohort,
        "file_format": file_format,
        "storage_platform": storage_platform,
        "cursor": cursor,
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
    if fields:
        params["fields"] = fields
    if hydrate:
        params["hydrate"] = True
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
        sort: DatasetListSortOption | None = None,
        cursor: str | None = None,
        offset: int | None = None,
        limit: int = 100,
        include_total: bool = True,
    ) -> CursorPaginatedResponse[DatasetWithRelationsResponse]:
        """List datasets, one page at a time.

        Pages either by keyset `cursor` or by `offset`, never both. Offset
        paging is fine for shallow pages but its cost grows with depth; past
        a few thousand records follow `next_cursor` instead, or use
        `iter_all()` to walk the whole result set.

        A cursor is only valid for the `sort` and filters it was issued
        with; changing either mid-walk raises `RecordValidationError` (422).
        Pass `include_total=False` to skip the count query, which leaves
        `total` as None on the response.
        """
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
            sort,
            cursor,
            offset,
            limit,
            include_total,
        )
        response = self._get(f"{_PREFIX}/", params=params)
        return CursorPaginatedResponse[DatasetWithRelationsResponse].model_validate(
            response.json()
        )

    def iter_all(
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
        sort: DatasetListSortOption | None = None,
        limit: int = 100,
    ) -> Iterator[DatasetWithRelationsResponse]:
        """Walk every matching dataset, following cursors until exhausted.

        Skips the total count, since the walk does not need it. Leaves
        `sort` to the server default unless one is passed; note that the
        server default sorts on a mutable key, so a row modified mid-walk
        can be skipped or repeated. Pass `DatasetListSortOption.newest` or
        `.oldest` to sort on the immutable `created_at` and avoid that.
        """
        cursor: str | None = None
        while True:
            page = self.list(
                canonical_id=canonical_id,
                version=version,
                modality=modality,
                project=project,
                access_scope=access_scope,
                is_latest=is_latest,
                exclude_tombstoned=exclude_tombstoned,
                include_lineage=include_lineage,
                include_collections=include_collections,
                sort=sort,
                cursor=cursor,
                limit=limit,
                include_total=False,
            )
            yield from page.results
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

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
        cohort: str | None = None,
        file_format: str | None = None,
        storage_platform: str | None = None,
        facets: _FacetList | None = None,
        fields: _FacetList | None = None,
        sort: DatasetSortOption | None = None,
        cursor: str | None = None,
        limit: int = 10,
        hydrate: bool = False,
    ) -> DatasetSearchResponse:
        """Full-text and faceted search over the dataset index.

        Paging is by cursor only — there is no offset. Pass the previous
        response's `next_cursor` to advance, and stop once it comes back
        None; `iter_search()` does that walk for you. Keep `sort` and the
        filters identical for the whole walk, since a cursor is only valid
        under the ones it was issued with.

        Results are lightweight `DatasetSearchHit` objects. Pass
        `fields=[...]` to add individual dataset fields to each hit, or
        `hydrate=True` to get full `DatasetResponse` records instead (one
        extra query per page, and `limit` is capped at 100).
        """
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
            cohort,
            file_format,
            storage_platform,
            facets,
            fields,
            sort,
            cursor,
            limit,
            hydrate,
        )
        response = self._get(f"{_PREFIX}/search/", params=params)
        return DatasetSearchResponse.model_validate(response.json())

    def iter_search(
        self,
        **kwargs: object,
    ) -> Iterator[DatasetResponse | DatasetSearchHit]:
        """Walk every search hit, following cursors until exhausted.

        Accepts the same keyword arguments as `search()`, except `cursor`,
        which this method manages.
        """
        if "cursor" in kwargs:
            raise ValueError("iter_search() manages the cursor; do not pass one")
        cursor: str | None = None
        while True:
            page = self.search(cursor=cursor, **kwargs)  # type: ignore[arg-type]
            yield from page.results
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

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
        sort: DatasetListSortOption | None = None,
        cursor: str | None = None,
        offset: int | None = None,
        limit: int = 100,
        include_total: bool = True,
    ) -> CursorPaginatedResponse[DatasetWithRelationsResponse]:
        """List datasets, one page at a time.

        Pages either by keyset `cursor` or by `offset`, never both. Offset
        paging is fine for shallow pages but its cost grows with depth; past
        a few thousand records follow `next_cursor` instead, or use
        `iter_all()` to walk the whole result set.

        A cursor is only valid for the `sort` and filters it was issued
        with; changing either mid-walk raises `RecordValidationError` (422).
        Pass `include_total=False` to skip the count query, which leaves
        `total` as None on the response.
        """
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
            sort,
            cursor,
            offset,
            limit,
            include_total,
        )
        response = await self._get(f"{_PREFIX}/", params=params)
        return CursorPaginatedResponse[DatasetWithRelationsResponse].model_validate(
            response.json()
        )

    async def iter_all(
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
        sort: DatasetListSortOption | None = None,
        limit: int = 100,
    ) -> AsyncIterator[DatasetWithRelationsResponse]:
        """Walk every matching dataset, following cursors until exhausted.

        Skips the total count, since the walk does not need it. Leaves
        `sort` to the server default unless one is passed; note that the
        server default sorts on a mutable key, so a row modified mid-walk
        can be skipped or repeated. Pass `DatasetListSortOption.newest` or
        `.oldest` to sort on the immutable `created_at` and avoid that.
        """
        cursor: str | None = None
        while True:
            page = await self.list(
                canonical_id=canonical_id,
                version=version,
                modality=modality,
                project=project,
                access_scope=access_scope,
                is_latest=is_latest,
                exclude_tombstoned=exclude_tombstoned,
                include_lineage=include_lineage,
                include_collections=include_collections,
                sort=sort,
                cursor=cursor,
                limit=limit,
                include_total=False,
            )
            for result in page.results:
                yield result
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

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
        cohort: str | None = None,
        file_format: str | None = None,
        storage_platform: str | None = None,
        facets: _FacetList | None = None,
        fields: _FacetList | None = None,
        sort: DatasetSortOption | None = None,
        cursor: str | None = None,
        limit: int = 10,
        hydrate: bool = False,
    ) -> DatasetSearchResponse:
        """Full-text and faceted search over the dataset index.

        Paging is by cursor only — there is no offset. Pass the previous
        response's `next_cursor` to advance, and stop once it comes back
        None; `iter_search()` does that walk for you. Keep `sort` and the
        filters identical for the whole walk, since a cursor is only valid
        under the ones it was issued with.

        Results are lightweight `DatasetSearchHit` objects. Pass
        `fields=[...]` to add individual dataset fields to each hit, or
        `hydrate=True` to get full `DatasetResponse` records instead (one
        extra query per page, and `limit` is capped at 100).
        """
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
            cohort,
            file_format,
            storage_platform,
            facets,
            fields,
            sort,
            cursor,
            limit,
            hydrate,
        )
        response = await self._get(f"{_PREFIX}/search/", params=params)
        return DatasetSearchResponse.model_validate(response.json())

    async def iter_search(
        self,
        **kwargs: object,
    ) -> AsyncIterator[DatasetResponse | DatasetSearchHit]:
        """Walk every search hit, following cursors until exhausted.

        Accepts the same keyword arguments as `search()`, except `cursor`,
        which this method manages.
        """
        if "cursor" in kwargs:
            raise ValueError("iter_search() manages the cursor; do not pass one")
        cursor: str | None = None
        while True:
            page = await self.search(cursor=cursor, **kwargs)  # type: ignore[arg-type]
            for result in page.results:
                yield result
            if page.next_cursor is None:
                return
            cursor = page.next_cursor

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
