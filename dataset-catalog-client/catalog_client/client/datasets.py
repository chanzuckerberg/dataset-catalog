"""Dataset sub-client (sync and async)."""

import datetime
from collections.abc import AsyncIterator, Iterator
from typing import Literal, overload

from catalog_client.client._base import _AsyncBase, _SyncBase
from catalog_client.exceptions import CatalogError, CatalogUsageError, NotFoundError
from catalog_client.models.asset import LocationScope, StoragePlatform
from catalog_client.models.copy import (
    CopyType,
    DatasetCopyRequest,
    DatasetCopyResponse,
)
from catalog_client.models.dataset import (
    AuditLogEventType,
    DatasetAuditLogResponse,
    DatasetListSortOption,
    DatasetModality,
    DatasetRef,
    DatasetRequest,
    DatasetResponse,
    DatasetResponseV2,
    DatasetSearchHit,
    DatasetSearchPage,
    DatasetSearchPageV2,
    DatasetSearchResponse,
    DatasetShape,
    DatasetSortOption,
    DatasetType,
    DatasetWithRelationsResponse,
    DatasetWithRelationsResponseV2,
)
from catalog_client.models.instance import (
    DatasetInstanceListResponse,
    DatasetInstanceResponse,
    DatasetInstanceUpdate,
    DatasetInstanceWithLocationsResponse,
    InstanceView,
)
from catalog_client.models.metadata import ObservationUnit
from catalog_client.models.pagination import CursorPaginatedResponse, PaginatedResponse

_PREFIX = "datasets"

# Server-side page-size ceilings, mirrored here so an oversized page fails
# before the round trip that would only return a 422.
_SEARCH_MAX_LIMIT = 1000
_LIST_MAX_LIMIT = 500

# `hydrate=True` re-reads every hit from the database, so the server caps the
# page size lower than the 1000 an unhydrated search allows.
_HYDRATED_MAX_LIMIT = 100

# Every resolve hit is a full dataset record, which is what holds its page
# size below the ceiling an unhydrated search allows.
_RESOLVE_MAX_LIMIT = 100

# Depth past which offset paging is refused in favour of a keyset cursor. The
# server accepts deeper offsets, but it walks and discards every skipped row,
# and a concurrent write shifts the window — so rows get skipped or repeated.
# A cursor is constant-cost at any depth and immune to that shift.
_MAX_OFFSET = 10_000


def _check_limit(limit: int, maximum: int, route: str) -> None:
    """Reject a page size the server would 422 on, without the round trip."""
    if limit < 1:
        raise CatalogUsageError(f"limit must be >= 1, got {limit}")
    if limit > maximum:
        raise CatalogUsageError(f"limit must be <= {maximum} on {route}, got {limit}")


def _validate_search_page(
    payload: object, hydrate: bool, shape: DatasetShape
) -> DatasetSearchPage | DatasetSearchPageV2:
    """Parse a search page against the shape `hydrate` actually asked for.

    Validating the branch explicitly rather than against a union is what
    makes a malformed hydrated record raise. `DatasetSearchHit` allows
    extras and requires few fields, so a union would quietly accept a
    half-built `DatasetResponse` as a hit and hand the caller lightweight
    results they never asked for.
    """
    if hydrate and shape is DatasetShape.v2:
        return DatasetSearchResponse[DatasetResponseV2].model_validate(payload)
    if hydrate:
        return DatasetSearchResponse[DatasetResponse].model_validate(payload)
    return DatasetSearchResponse[DatasetSearchHit].model_validate(payload)


def _next_cursor(
    following: str | None, current: str | None, page_size: int
) -> str | None:
    """Return the cursor for the next page, or None once the walk is done.

    Guards the two ways a server can turn a cursor walk into an unbounded
    request loop: handing back the cursor it was just given, or promising
    more pages while returning none of them. Both are server faults, not
    caller mistakes, so they surface as `CatalogError`.
    """
    if following is None:
        return None
    if following == current:
        raise CatalogError(
            f"server returned the same cursor ({following!r}) twice; "
            "aborting the walk rather than paging forever"
        )
    if page_size == 0:
        raise CatalogError(
            "server returned an empty page with a non-null next_cursor; "
            "aborting the walk rather than paging forever"
        )
    return following


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
    _check_limit(limit, _LIST_MAX_LIMIT, "datasets.list()")
    if cursor is not None and offset is not None:
        raise CatalogUsageError(
            "cursor and offset are mutually exclusive; pass only one "
            "(prefer cursor past a few thousand records)"
        )
    if offset is not None and offset < 0:
        raise CatalogUsageError(f"offset must be >= 0, got {offset}")
    if offset is not None and offset > _MAX_OFFSET:
        raise CatalogUsageError(
            f"offset {offset} exceeds the maximum of {_MAX_OFFSET}. Page this "
            "deep with the keyset cursor instead: pass the previous "
            "response's next_cursor as cursor= (CLI: --cursor), or walk the "
            "whole result set with iter_all(). Offset paging at this depth is "
            "slow and can skip or repeat rows when records change mid-walk."
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
    dataset_type: DatasetType | None,
    observation_unit: ObservationUnit | None,
    is_combined: bool | None,
    uri_prefix: str | None,
    facets: list[str] | None,
    fields: list[str] | None,
    sort: DatasetSortOption | None,
    cursor: str | None,
    limit: int,
    hydrate: bool,
) -> dict:
    if hydrate and limit > _HYDRATED_MAX_LIMIT:
        raise CatalogUsageError(
            f"limit must be <= {_HYDRATED_MAX_LIMIT} when hydrate=True, got {limit}"
        )
    _check_limit(limit, _SEARCH_MAX_LIMIT, "datasets.search()")
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
        "uri_prefix": uri_prefix,
        "cursor": cursor,
    }
    for key, value in optional.items():
        if value is not None:
            params[key] = value
    if modality is not None:
        params["modality"] = modality.value
    if dataset_type is not None:
        params["dataset_type"] = dataset_type.value
    if observation_unit is not None:
        params["observation_unit"] = observation_unit.value
    if is_latest is not None:
        params["is_latest"] = is_latest
    if is_combined is not None:
        params["is_combined"] = is_combined
    if facets:
        params["facets"] = facets
    if fields:
        params["fields"] = fields
    if hydrate:
        params["hydrate"] = True
    return params


def _build_resolve_params(
    uri: str,
    scope: LocationScope,
    storage_platform: StoragePlatform | None,
    cursor: str | None,
    limit: int,
) -> dict:
    _check_limit(limit, _RESOLVE_MAX_LIMIT, "datasets.resolve()")
    params: dict = {"uri": uri, "scope": scope.value, "limit": limit}
    if storage_platform is not None:
        params["storage_platform"] = storage_platform.value
    if cursor is not None:
        params["cursor"] = cursor
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


def _shape_params(shape: DatasetShape) -> dict:
    # v1 is the server default; leaving it off keeps v1 requests unchanged.
    return {"shape": "v2"} if DatasetShape(shape) is DatasetShape.v2 else {}


def _build_view_params(
    shape: DatasetShape,
    instance: InstanceView | None,
    root_uri: str | None,
    storage_platform: StoragePlatform | str | None,
    *,
    send_platform: bool,
) -> dict:
    """Query params choosing the dataset body and which instances it carries.

    `send_platform` is False on search and resolve, where `storage_platform`
    is already sent as the location filter and doubles as the instance
    filter; on get and list it only selects instances, so it is sent here.
    Misuse is rejected locally with the message the server's 422 carries.
    """
    shape = DatasetShape(shape)
    filtering = instance is InstanceView.filter
    if filtering and root_uri is None and storage_platform is None:
        raise CatalogUsageError(
            "instance=InstanceView.filter needs storage_platform, root_uri, or both"
        )
    if not filtering and root_uri is not None:
        raise CatalogUsageError(
            "root_uri selects instances only with instance=InstanceView.filter"
        )
    if send_platform and not filtering and storage_platform is not None:
        raise CatalogUsageError(
            "storage_platform selects instances only with instance=InstanceView.filter"
        )
    params = _shape_params(shape)
    if instance is not None:
        params["instance"] = instance.value
    if root_uri is not None:
        params["root_uri"] = root_uri
    if send_platform and storage_platform is not None:
        params["storage_platform"] = StoragePlatform(storage_platform).value
    return params


def _build_instance_list_params(
    storage_platform: StoragePlatform | None,
    is_primary: bool | None,
    include_tombstoned: bool,
) -> dict:
    params: dict = {}
    if storage_platform is not None:
        params["storage_platform"] = storage_platform.value
    if is_primary is not None:
        params["is_primary"] = is_primary
    if include_tombstoned:
        params["include_tombstoned"] = True
    return params


def _dataset_model(shape: DatasetShape) -> type[DatasetResponse | DatasetResponseV2]:
    return DatasetResponseV2 if shape is DatasetShape.v2 else DatasetResponse


def _list_page_model(
    shape: DatasetShape,
) -> type[
    CursorPaginatedResponse[DatasetWithRelationsResponse]
    | CursorPaginatedResponse[DatasetWithRelationsResponseV2]
]:
    if shape is DatasetShape.v2:
        return CursorPaginatedResponse[DatasetWithRelationsResponseV2]
    return CursorPaginatedResponse[DatasetWithRelationsResponse]


def _resolve_page_model(
    shape: DatasetShape,
) -> type[
    DatasetSearchResponse[DatasetResponse] | DatasetSearchResponse[DatasetResponseV2]
]:
    if shape is DatasetShape.v2:
        return DatasetSearchResponse[DatasetResponseV2]
    return DatasetSearchResponse[DatasetResponse]


def _dataset_with_relations_model(
    shape: DatasetShape,
) -> type[DatasetWithRelationsResponse | DatasetWithRelationsResponseV2]:
    if shape is DatasetShape.v2:
        return DatasetWithRelationsResponseV2
    return DatasetWithRelationsResponse


class DatasetClient(_SyncBase):
    @overload
    def list(
        self,
        *,
        canonical_id: str | None = ...,
        version: str | None = ...,
        modality: DatasetModality | None = ...,
        project: str | None = ...,
        access_scope: str | None = ...,
        is_latest: bool | None = ...,
        exclude_tombstoned: bool = ...,
        include_lineage: bool = ...,
        include_collections: bool = ...,
        sort: DatasetListSortOption | None = ...,
        cursor: str | None = ...,
        offset: int | None = ...,
        limit: int = ...,
        include_total: bool = ...,
        shape: Literal[DatasetShape.v1] = ...,
        instance: InstanceView | None = ...,
        storage_platform: StoragePlatform | None = ...,
        root_uri: str | None = ...,
    ) -> CursorPaginatedResponse[DatasetWithRelationsResponse]: ...

    @overload
    def list(
        self,
        *,
        canonical_id: str | None = ...,
        version: str | None = ...,
        modality: DatasetModality | None = ...,
        project: str | None = ...,
        access_scope: str | None = ...,
        is_latest: bool | None = ...,
        exclude_tombstoned: bool = ...,
        include_lineage: bool = ...,
        include_collections: bool = ...,
        sort: DatasetListSortOption | None = ...,
        cursor: str | None = ...,
        offset: int | None = ...,
        limit: int = ...,
        include_total: bool = ...,
        shape: Literal[DatasetShape.v2],
        instance: InstanceView | None = ...,
        storage_platform: StoragePlatform | None = ...,
        root_uri: str | None = ...,
    ) -> CursorPaginatedResponse[DatasetWithRelationsResponseV2]: ...

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
        shape: DatasetShape = DatasetShape.v1,
        instance: InstanceView | None = None,
        storage_platform: StoragePlatform | None = None,
        root_uri: str | None = None,
    ) -> (
        CursorPaginatedResponse[DatasetWithRelationsResponse]
        | CursorPaginatedResponse[DatasetWithRelationsResponseV2]
    ):
        """List datasets, one page at a time.

        Pages either by keyset `cursor` or by `offset`, never both. Offset
        paging is fine for shallow pages but its cost grows with depth, and
        an `offset` above 10,000 raises `ValueError` — past that, follow
        `next_cursor` instead, or use `iter_all()` to walk the whole result
        set.

        A cursor is only valid for the `sort` and filters it was issued
        with; changing either mid-walk raises `RecordValidationError` (422).
        Pass `include_total=False` to skip the count query, which leaves
        `total` as None on the response.

        `shape=DatasetShape.v2` returns `DatasetWithRelationsResponseV2`,
        which drops the flat `locations`. `instance` picks which copies each
        record carries; `storage_platform` and `root_uri` narrow them and
        need `instance=InstanceView.filter` — they do not filter datasets.
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
        params.update(
            _build_view_params(
                shape, instance, root_uri, storage_platform, send_platform=True
            )
        )
        response = self._get(f"{_PREFIX}/", params=params)
        return _list_page_model(DatasetShape(shape)).model_validate(response.json())

    @overload
    def iter_all(
        self,
        *,
        canonical_id: str | None = ...,
        version: str | None = ...,
        modality: DatasetModality | None = ...,
        project: str | None = ...,
        access_scope: str | None = ...,
        is_latest: bool | None = ...,
        exclude_tombstoned: bool = ...,
        include_lineage: bool = ...,
        include_collections: bool = ...,
        sort: DatasetListSortOption | None = ...,
        limit: int = ...,
        shape: Literal[DatasetShape.v1] = ...,
        instance: InstanceView | None = ...,
        storage_platform: StoragePlatform | None = ...,
        root_uri: str | None = ...,
    ) -> Iterator[DatasetWithRelationsResponse]: ...

    @overload
    def iter_all(
        self,
        *,
        canonical_id: str | None = ...,
        version: str | None = ...,
        modality: DatasetModality | None = ...,
        project: str | None = ...,
        access_scope: str | None = ...,
        is_latest: bool | None = ...,
        exclude_tombstoned: bool = ...,
        include_lineage: bool = ...,
        include_collections: bool = ...,
        sort: DatasetListSortOption | None = ...,
        limit: int = ...,
        shape: Literal[DatasetShape.v2],
        instance: InstanceView | None = ...,
        storage_platform: StoragePlatform | None = ...,
        root_uri: str | None = ...,
    ) -> Iterator[DatasetWithRelationsResponseV2]: ...

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
        shape: DatasetShape = DatasetShape.v1,
        instance: InstanceView | None = None,
        storage_platform: StoragePlatform | None = None,
        root_uri: str | None = None,
    ) -> Iterator[DatasetWithRelationsResponse | DatasetWithRelationsResponseV2]:
        """Walk every matching dataset, following cursors until exhausted.

        Skips the total count, since the walk does not need it. Leaves
        `sort` to the server default unless one is passed; note that the
        server default sorts on a mutable key, so a row modified mid-walk
        can be skipped or repeated. Pass `DatasetListSortOption.newest` or
        `.oldest` to sort on the immutable `created_at` and avoid that.
        """
        cursor: str | None = None
        while True:
            page = self.list(  # type: ignore[call-overload, misc]
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
                shape=shape,
                instance=instance,
                storage_platform=storage_platform,
                root_uri=root_uri,
            )
            yield from page.results
            following = _next_cursor(page.next_cursor, cursor, len(page.results))
            if following is None:
                return
            cursor = following

    @overload
    def search(
        self,
        *,
        q: str | None = ...,
        modality: DatasetModality | None = ...,
        project: str | None = ...,
        is_latest: bool | None = ...,
        access_scope: str | None = ...,
        organism: str | None = ...,
        tissue: str | None = ...,
        sub_modality: str | None = ...,
        assay: str | None = ...,
        disease: str | None = ...,
        development_stage: str | None = ...,
        cohort: str | None = ...,
        file_format: str | None = ...,
        storage_platform: str | None = ...,
        dataset_type: DatasetType | None = ...,
        observation_unit: ObservationUnit | None = ...,
        is_combined: bool | None = ...,
        uri_prefix: str | None = ...,
        facets: _FacetList | None = ...,
        fields: _FacetList | None = ...,
        sort: DatasetSortOption | None = ...,
        cursor: str | None = ...,
        limit: int = ...,
        hydrate: bool = ...,
        shape: Literal[DatasetShape.v1] = ...,
        instance: InstanceView | None = ...,
        root_uri: str | None = ...,
    ) -> DatasetSearchPage: ...

    @overload
    def search(
        self,
        *,
        q: str | None = ...,
        modality: DatasetModality | None = ...,
        project: str | None = ...,
        is_latest: bool | None = ...,
        access_scope: str | None = ...,
        organism: str | None = ...,
        tissue: str | None = ...,
        sub_modality: str | None = ...,
        assay: str | None = ...,
        disease: str | None = ...,
        development_stage: str | None = ...,
        cohort: str | None = ...,
        file_format: str | None = ...,
        storage_platform: str | None = ...,
        dataset_type: DatasetType | None = ...,
        observation_unit: ObservationUnit | None = ...,
        is_combined: bool | None = ...,
        uri_prefix: str | None = ...,
        facets: _FacetList | None = ...,
        fields: _FacetList | None = ...,
        sort: DatasetSortOption | None = ...,
        cursor: str | None = ...,
        limit: int = ...,
        hydrate: bool = ...,
        shape: Literal[DatasetShape.v2],
        instance: InstanceView | None = ...,
        root_uri: str | None = ...,
    ) -> DatasetSearchPageV2: ...

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
        dataset_type: DatasetType | None = None,
        observation_unit: ObservationUnit | None = None,
        is_combined: bool | None = None,
        uri_prefix: str | None = None,
        facets: _FacetList | None = None,
        fields: _FacetList | None = None,
        sort: DatasetSortOption | None = None,
        cursor: str | None = None,
        limit: int = 10,
        hydrate: bool = False,
        shape: DatasetShape = DatasetShape.v1,
        instance: InstanceView | None = None,
        root_uri: str | None = None,
    ) -> DatasetSearchPage | DatasetSearchPageV2:
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

        `shape`, `instance` and `root_uri` only shape hydrated records —
        `DatasetResponseV2` under `shape=DatasetShape.v2`. With
        `instance=InstanceView.filter`, `storage_platform` narrows the
        instances as well as the matches.
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
            dataset_type,
            observation_unit,
            is_combined,
            uri_prefix,
            facets,
            fields,
            sort,
            cursor,
            limit,
            hydrate,
        )
        params.update(
            _build_view_params(
                shape, instance, root_uri, storage_platform, send_platform=False
            )
        )
        response = self._get(f"{_PREFIX}/search/", params=params)
        return _validate_search_page(response.json(), hydrate, DatasetShape(shape))

    @overload
    def iter_search(
        self,
        *,
        shape: Literal[DatasetShape.v1] = ...,
        **kwargs: object,
    ) -> Iterator[DatasetResponse | DatasetSearchHit]: ...

    @overload
    def iter_search(
        self,
        *,
        shape: Literal[DatasetShape.v2],
        **kwargs: object,
    ) -> Iterator[DatasetResponseV2 | DatasetSearchHit]: ...

    def iter_search(
        self,
        *,
        shape: DatasetShape = DatasetShape.v1,
        **kwargs: object,
    ) -> Iterator[DatasetResponse | DatasetResponseV2 | DatasetSearchHit]:
        """Walk every search hit, following cursors until exhausted.

        Accepts the same keyword arguments as `search()`, except `cursor`,
        which this method manages.
        """
        if "cursor" in kwargs:
            raise CatalogUsageError("iter_search() manages the cursor; do not pass one")
        cursor: str | None = None
        while True:
            page = self.search(cursor=cursor, shape=shape, **kwargs)  # type: ignore[call-overload]
            yield from page.results
            following = _next_cursor(page.next_cursor, cursor, len(page.results))
            if following is None:
                return
            cursor = following

    @overload
    def resolve(
        self,
        uri: str,
        *,
        scope: LocationScope = ...,
        storage_platform: StoragePlatform | None = ...,
        cursor: str | None = ...,
        limit: int = ...,
        shape: Literal[DatasetShape.v1] = ...,
        instance: InstanceView | None = ...,
        root_uri: str | None = ...,
    ) -> DatasetSearchResponse[DatasetResponse]: ...

    @overload
    def resolve(
        self,
        uri: str,
        *,
        scope: LocationScope = ...,
        storage_platform: StoragePlatform | None = ...,
        cursor: str | None = ...,
        limit: int = ...,
        shape: Literal[DatasetShape.v2],
        instance: InstanceView | None = ...,
        root_uri: str | None = ...,
    ) -> DatasetSearchResponse[DatasetResponseV2]: ...

    def resolve(
        self,
        uri: str,
        *,
        scope: LocationScope = LocationScope.exact,
        storage_platform: StoragePlatform | None = None,
        cursor: str | None = None,
        limit: int = 50,
        shape: DatasetShape = DatasetShape.v1,
        instance: InstanceView | None = None,
        root_uri: str | None = None,
    ) -> (
        DatasetSearchResponse[DatasetResponse]
        | DatasetSearchResponse[DatasetResponseV2]
    ):
        """Resolve a file or directory URI to the dataset(s) registered at it.

        By default the match is the URI itself. `scope=ancestor` walks *up*,
        so a deep object key finds the dataset registered on a parent
        directory, closest match first; `scope=descendant` walks *down* and
        comes back in `id` order, since no match there outranks another.

        Pass `storage_platform` whenever the URI is a bare POSIX path: every
        HPC cluster mounts its own `/hpc/projects/x`, so without it the path
        resolves across all of them.

        Pages by cursor only. Keep `uri`, `scope` and `storage_platform`
        identical for the whole walk, or use `iter_resolve()`, which manages
        the cursor for you.

        Each record carries the instances the URI matched through, unless
        `instance` says otherwise; `shape=DatasetShape.v2` returns
        `DatasetResponseV2`.

        A deployment predating this route answers `NotFoundError: Dataset
        'resolve' not found` — the path falls through to the by-id route.
        That is a missing endpoint, not an unregistered URI.
        """
        params = _build_resolve_params(uri, scope, storage_platform, cursor, limit)
        params.update(
            _build_view_params(
                shape, instance, root_uri, storage_platform, send_platform=False
            )
        )
        response = self._get(f"{_PREFIX}/resolve", params=params)
        return _resolve_page_model(DatasetShape(shape)).model_validate(response.json())

    @overload
    def iter_resolve(
        self,
        uri: str,
        *,
        scope: LocationScope = ...,
        storage_platform: StoragePlatform | None = ...,
        limit: int = ...,
        shape: Literal[DatasetShape.v1] = ...,
        instance: InstanceView | None = ...,
        root_uri: str | None = ...,
    ) -> Iterator[DatasetResponse]: ...

    @overload
    def iter_resolve(
        self,
        uri: str,
        *,
        scope: LocationScope = ...,
        storage_platform: StoragePlatform | None = ...,
        limit: int = ...,
        shape: Literal[DatasetShape.v2],
        instance: InstanceView | None = ...,
        root_uri: str | None = ...,
    ) -> Iterator[DatasetResponseV2]: ...

    def iter_resolve(
        self,
        uri: str,
        *,
        scope: LocationScope = LocationScope.exact,
        storage_platform: StoragePlatform | None = None,
        limit: int = 50,
        shape: DatasetShape = DatasetShape.v1,
        instance: InstanceView | None = None,
        root_uri: str | None = None,
    ) -> Iterator[DatasetResponse | DatasetResponseV2]:
        """Walk every dataset the URI resolves to, following cursors until exhausted."""
        cursor: str | None = None
        while True:
            page = self.resolve(  # type: ignore[call-overload]
                uri,
                scope=scope,
                storage_platform=storage_platform,
                cursor=cursor,
                limit=limit,
                shape=shape,
                instance=instance,
                root_uri=root_uri,
            )
            yield from page.results
            following = _next_cursor(page.next_cursor, cursor, len(page.results))
            if following is None:
                return
            cursor = following

    def copy(
        self,
        dataset_id: str,
        request: DatasetCopyRequest,
        *,
        copy_type: CopyType,
    ) -> DatasetCopyResponse:
        """Register the catalog side of a completed transfer of `dataset_id`.

        `copy_type` is required — the catalog never infers it from the
        destination or the body. A `fork` becomes a dataset of its own,
        written in one transaction with the `copy_of` edge tying it to the
        source (`lineage_edge_id` on the response). A `mirror` becomes
        another instance of the same dataset, with no edge (`instance_id`
        on the response); its identity fields must equal the source's.

        Replaying is safe: the destination identity is the idempotency key,
        so a replay returns the same ids and writes nothing, whatever its
        entries now say. Correct a fork with `update()` and a mirror with
        `update_instance()`, not by replaying with changed entries.

        A refusal raises `CopyError`, whose `code` says why and whose
        `retryable` says whether retrying the same request can help.
        """
        response = self._post(
            f"{_PREFIX}/{dataset_id}/copy",
            params={"copy_type": copy_type.value},
            # exclude_none: lineage_metadata is stored untouched, so a null
            # the caller never set would be stored as one.
            json=request.model_dump(mode="json", exclude_none=True),
        )
        return DatasetCopyResponse.model_validate(response.json())

    def list_instances(
        self,
        dataset_id: str,
        *,
        storage_platform: StoragePlatform | None = None,
        is_primary: bool | None = None,
        include_tombstoned: bool = False,
    ) -> DatasetInstanceListResponse:
        """Every copy of a dataset's bytes, primary first, each with its assets.

        Not paginated. Pass `include_tombstoned=True` when tracing where a
        copy came from: `copied_from_instance_id` keeps pointing at an
        instance after it is removed.
        """
        params = _build_instance_list_params(
            storage_platform, is_primary, include_tombstoned
        )
        response = self._get(f"{_PREFIX}/{dataset_id}/instances", params=params)
        return DatasetInstanceListResponse.model_validate(response.json())

    def get_instance(
        self, dataset_id: str, instance_id: str
    ) -> DatasetInstanceWithLocationsResponse:
        response = self._get(f"{_PREFIX}/{dataset_id}/instances/{instance_id}")
        return DatasetInstanceWithLocationsResponse.model_validate(response.json())

    def update_instance(
        self, dataset_id: str, instance_id: str, update: DatasetInstanceUpdate
    ) -> DatasetInstanceWithLocationsResponse:
        """Fill in a partial mirror or fix a copy in place.

        Locations are matched by `location_uri`; omitted assets stay — remove
        one with `delete_instance_asset()`.
        """
        response = self._patch(
            f"{_PREFIX}/{dataset_id}/instances/{instance_id}",
            json=update.model_dump(mode="json", exclude_unset=True),
        )
        return DatasetInstanceWithLocationsResponse.model_validate(response.json())

    def delete_instance(self, dataset_id: str, instance_id: str) -> None:
        """Tombstone one copy and its assets.

        The server refuses the primary with HTTP 409: promote another
        instance first, or delete the dataset.
        """
        self._delete(f"{_PREFIX}/{dataset_id}/instances/{instance_id}")

    def promote_instance(
        self, dataset_id: str, instance_id: str
    ) -> DatasetInstanceResponse:
        """Make this instance the authoritative copy, demoting the current primary."""
        response = self._post(f"{_PREFIX}/{dataset_id}/instances/{instance_id}/promote")
        return DatasetInstanceResponse.model_validate(response.json())

    def delete_instance_asset(
        self, dataset_id: str, instance_id: str, asset_id: str
    ) -> None:
        """Tombstone one asset of one copy.

        The server refuses an instance's last live asset with HTTP 409.
        Removing a primary asset does not cascade to the mirrors.
        """
        self._delete(
            f"{_PREFIX}/{dataset_id}/instances/{instance_id}/assets/{asset_id}"
        )

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

    @overload
    def get(
        self,
        ref: str | DatasetRef,
        *,
        exclude_tombstoned: bool = ...,
        include_lineage: bool = ...,
        include_collections: bool = ...,
        shape: Literal[DatasetShape.v1] = ...,
        instance: InstanceView | None = ...,
        storage_platform: StoragePlatform | None = ...,
        root_uri: str | None = ...,
    ) -> DatasetWithRelationsResponse: ...

    @overload
    def get(
        self,
        ref: str | DatasetRef,
        *,
        exclude_tombstoned: bool = ...,
        include_lineage: bool = ...,
        include_collections: bool = ...,
        shape: Literal[DatasetShape.v2],
        instance: InstanceView | None = ...,
        storage_platform: StoragePlatform | None = ...,
        root_uri: str | None = ...,
    ) -> DatasetWithRelationsResponseV2: ...

    def get(
        self,
        ref: str | DatasetRef,
        *,
        exclude_tombstoned: bool = True,
        include_lineage: bool = False,
        include_collections: bool = False,
        shape: DatasetShape = DatasetShape.v1,
        instance: InstanceView | None = None,
        storage_platform: StoragePlatform | None = None,
        root_uri: str | None = None,
    ) -> DatasetWithRelationsResponse | DatasetWithRelationsResponseV2:
        """Fetch one dataset.

        `shape=DatasetShape.v2` returns `DatasetWithRelationsResponseV2`,
        which drops the flat `locations`. `instance` picks which copies the
        record carries; `storage_platform` and `root_uri` need
        `instance=InstanceView.filter`.
        """
        params = _build_view_params(
            shape, instance, root_uri, storage_platform, send_platform=True
        )
        dataset_id = ref if isinstance(ref, str) else self._resolve(ref)
        if not exclude_tombstoned:
            params["exclude_tombstoned"] = False
        if include_lineage:
            params["include_lineage"] = True
        if include_collections:
            params["include_collections"] = True
        response = self._get(f"{_PREFIX}/{dataset_id}", params=params)
        return _dataset_with_relations_model(DatasetShape(shape)).model_validate(
            response.json()
        )

    @overload
    def create(
        self,
        dataset: DatasetRequest,
        *,
        shape: Literal[DatasetShape.v1] = ...,
    ) -> DatasetResponse: ...

    @overload
    def create(
        self,
        dataset: DatasetRequest,
        *,
        shape: Literal[DatasetShape.v2],
    ) -> DatasetResponseV2: ...

    def create(
        self,
        dataset: DatasetRequest,
        *,
        shape: DatasetShape = DatasetShape.v1,
    ) -> DatasetResponse | DatasetResponseV2:
        response = self._post(
            f"{_PREFIX}/",
            params=_shape_params(shape),
            json=dataset.model_dump(mode="json"),
        )
        return _dataset_model(DatasetShape(shape)).model_validate(response.json())

    @overload
    def update(
        self,
        ref: str | DatasetRef,
        dataset: DatasetRequest,
        *,
        shape: Literal[DatasetShape.v1] = ...,
    ) -> DatasetResponse: ...

    @overload
    def update(
        self,
        ref: str | DatasetRef,
        dataset: DatasetRequest,
        *,
        shape: Literal[DatasetShape.v2],
    ) -> DatasetResponseV2: ...

    def update(
        self,
        ref: str | DatasetRef,
        dataset: DatasetRequest,
        *,
        shape: DatasetShape = DatasetShape.v1,
    ) -> DatasetResponse | DatasetResponseV2:
        dataset_id = ref if isinstance(ref, str) else self._resolve(ref)
        response = self._patch(
            f"{_PREFIX}/{dataset_id}",
            params=_shape_params(shape),
            json=dataset.model_dump(mode="json", exclude_unset=True),
        )
        return _dataset_model(DatasetShape(shape)).model_validate(response.json())

    def delete(self, ref: str | DatasetRef) -> None:
        dataset_id = ref if isinstance(ref, str) else self._resolve(ref)
        self._delete(f"{_PREFIX}/{dataset_id}")


class AsyncDatasetClient(_AsyncBase):
    @overload
    async def list(
        self,
        *,
        canonical_id: str | None = ...,
        version: str | None = ...,
        modality: DatasetModality | None = ...,
        project: str | None = ...,
        access_scope: str | None = ...,
        is_latest: bool | None = ...,
        exclude_tombstoned: bool = ...,
        include_lineage: bool = ...,
        include_collections: bool = ...,
        sort: DatasetListSortOption | None = ...,
        cursor: str | None = ...,
        offset: int | None = ...,
        limit: int = ...,
        include_total: bool = ...,
        shape: Literal[DatasetShape.v1] = ...,
        instance: InstanceView | None = ...,
        storage_platform: StoragePlatform | None = ...,
        root_uri: str | None = ...,
    ) -> CursorPaginatedResponse[DatasetWithRelationsResponse]: ...

    @overload
    async def list(
        self,
        *,
        canonical_id: str | None = ...,
        version: str | None = ...,
        modality: DatasetModality | None = ...,
        project: str | None = ...,
        access_scope: str | None = ...,
        is_latest: bool | None = ...,
        exclude_tombstoned: bool = ...,
        include_lineage: bool = ...,
        include_collections: bool = ...,
        sort: DatasetListSortOption | None = ...,
        cursor: str | None = ...,
        offset: int | None = ...,
        limit: int = ...,
        include_total: bool = ...,
        shape: Literal[DatasetShape.v2],
        instance: InstanceView | None = ...,
        storage_platform: StoragePlatform | None = ...,
        root_uri: str | None = ...,
    ) -> CursorPaginatedResponse[DatasetWithRelationsResponseV2]: ...

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
        shape: DatasetShape = DatasetShape.v1,
        instance: InstanceView | None = None,
        storage_platform: StoragePlatform | None = None,
        root_uri: str | None = None,
    ) -> (
        CursorPaginatedResponse[DatasetWithRelationsResponse]
        | CursorPaginatedResponse[DatasetWithRelationsResponseV2]
    ):
        """List datasets, one page at a time.

        Pages either by keyset `cursor` or by `offset`, never both. Offset
        paging is fine for shallow pages but its cost grows with depth, and
        an `offset` above 10,000 raises `ValueError` — past that, follow
        `next_cursor` instead, or use `iter_all()` to walk the whole result
        set.

        A cursor is only valid for the `sort` and filters it was issued
        with; changing either mid-walk raises `RecordValidationError` (422).
        Pass `include_total=False` to skip the count query, which leaves
        `total` as None on the response.

        `shape=DatasetShape.v2` returns `DatasetWithRelationsResponseV2`,
        which drops the flat `locations`. `instance` picks which copies each
        record carries; `storage_platform` and `root_uri` narrow them and
        need `instance=InstanceView.filter` — they do not filter datasets.
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
        params.update(
            _build_view_params(
                shape, instance, root_uri, storage_platform, send_platform=True
            )
        )
        response = await self._get(f"{_PREFIX}/", params=params)
        return _list_page_model(DatasetShape(shape)).model_validate(response.json())

    @overload
    def iter_all(
        self,
        *,
        canonical_id: str | None = ...,
        version: str | None = ...,
        modality: DatasetModality | None = ...,
        project: str | None = ...,
        access_scope: str | None = ...,
        is_latest: bool | None = ...,
        exclude_tombstoned: bool = ...,
        include_lineage: bool = ...,
        include_collections: bool = ...,
        sort: DatasetListSortOption | None = ...,
        limit: int = ...,
        shape: Literal[DatasetShape.v1] = ...,
        instance: InstanceView | None = ...,
        storage_platform: StoragePlatform | None = ...,
        root_uri: str | None = ...,
    ) -> AsyncIterator[DatasetWithRelationsResponse]: ...

    @overload
    def iter_all(
        self,
        *,
        canonical_id: str | None = ...,
        version: str | None = ...,
        modality: DatasetModality | None = ...,
        project: str | None = ...,
        access_scope: str | None = ...,
        is_latest: bool | None = ...,
        exclude_tombstoned: bool = ...,
        include_lineage: bool = ...,
        include_collections: bool = ...,
        sort: DatasetListSortOption | None = ...,
        limit: int = ...,
        shape: Literal[DatasetShape.v2],
        instance: InstanceView | None = ...,
        storage_platform: StoragePlatform | None = ...,
        root_uri: str | None = ...,
    ) -> AsyncIterator[DatasetWithRelationsResponseV2]: ...

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
        shape: DatasetShape = DatasetShape.v1,
        instance: InstanceView | None = None,
        storage_platform: StoragePlatform | None = None,
        root_uri: str | None = None,
    ) -> AsyncIterator[DatasetWithRelationsResponse | DatasetWithRelationsResponseV2]:
        """Walk every matching dataset, following cursors until exhausted.

        Skips the total count, since the walk does not need it. Leaves
        `sort` to the server default unless one is passed; note that the
        server default sorts on a mutable key, so a row modified mid-walk
        can be skipped or repeated. Pass `DatasetListSortOption.newest` or
        `.oldest` to sort on the immutable `created_at` and avoid that.
        """
        cursor: str | None = None
        while True:
            page = await self.list(  # type: ignore[call-overload, misc]
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
                shape=shape,
                instance=instance,
                storage_platform=storage_platform,
                root_uri=root_uri,
            )
            for result in page.results:
                yield result
            following = _next_cursor(page.next_cursor, cursor, len(page.results))
            if following is None:
                return
            cursor = following

    @overload
    async def search(
        self,
        *,
        q: str | None = ...,
        modality: DatasetModality | None = ...,
        project: str | None = ...,
        is_latest: bool | None = ...,
        access_scope: str | None = ...,
        organism: str | None = ...,
        tissue: str | None = ...,
        sub_modality: str | None = ...,
        assay: str | None = ...,
        disease: str | None = ...,
        development_stage: str | None = ...,
        cohort: str | None = ...,
        file_format: str | None = ...,
        storage_platform: str | None = ...,
        dataset_type: DatasetType | None = ...,
        observation_unit: ObservationUnit | None = ...,
        is_combined: bool | None = ...,
        uri_prefix: str | None = ...,
        facets: _FacetList | None = ...,
        fields: _FacetList | None = ...,
        sort: DatasetSortOption | None = ...,
        cursor: str | None = ...,
        limit: int = ...,
        hydrate: bool = ...,
        shape: Literal[DatasetShape.v1] = ...,
        instance: InstanceView | None = ...,
        root_uri: str | None = ...,
    ) -> DatasetSearchPage: ...

    @overload
    async def search(
        self,
        *,
        q: str | None = ...,
        modality: DatasetModality | None = ...,
        project: str | None = ...,
        is_latest: bool | None = ...,
        access_scope: str | None = ...,
        organism: str | None = ...,
        tissue: str | None = ...,
        sub_modality: str | None = ...,
        assay: str | None = ...,
        disease: str | None = ...,
        development_stage: str | None = ...,
        cohort: str | None = ...,
        file_format: str | None = ...,
        storage_platform: str | None = ...,
        dataset_type: DatasetType | None = ...,
        observation_unit: ObservationUnit | None = ...,
        is_combined: bool | None = ...,
        uri_prefix: str | None = ...,
        facets: _FacetList | None = ...,
        fields: _FacetList | None = ...,
        sort: DatasetSortOption | None = ...,
        cursor: str | None = ...,
        limit: int = ...,
        hydrate: bool = ...,
        shape: Literal[DatasetShape.v2],
        instance: InstanceView | None = ...,
        root_uri: str | None = ...,
    ) -> DatasetSearchPageV2: ...

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
        dataset_type: DatasetType | None = None,
        observation_unit: ObservationUnit | None = None,
        is_combined: bool | None = None,
        uri_prefix: str | None = None,
        facets: _FacetList | None = None,
        fields: _FacetList | None = None,
        sort: DatasetSortOption | None = None,
        cursor: str | None = None,
        limit: int = 10,
        hydrate: bool = False,
        shape: DatasetShape = DatasetShape.v1,
        instance: InstanceView | None = None,
        root_uri: str | None = None,
    ) -> DatasetSearchPage | DatasetSearchPageV2:
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

        `shape`, `instance` and `root_uri` only shape hydrated records —
        `DatasetResponseV2` under `shape=DatasetShape.v2`. With
        `instance=InstanceView.filter`, `storage_platform` narrows the
        instances as well as the matches.
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
            dataset_type,
            observation_unit,
            is_combined,
            uri_prefix,
            facets,
            fields,
            sort,
            cursor,
            limit,
            hydrate,
        )
        params.update(
            _build_view_params(
                shape, instance, root_uri, storage_platform, send_platform=False
            )
        )
        response = await self._get(f"{_PREFIX}/search/", params=params)
        return _validate_search_page(response.json(), hydrate, DatasetShape(shape))

    @overload
    def iter_search(
        self,
        *,
        shape: Literal[DatasetShape.v1] = ...,
        **kwargs: object,
    ) -> AsyncIterator[DatasetResponse | DatasetSearchHit]: ...

    @overload
    def iter_search(
        self,
        *,
        shape: Literal[DatasetShape.v2],
        **kwargs: object,
    ) -> AsyncIterator[DatasetResponseV2 | DatasetSearchHit]: ...

    async def iter_search(
        self,
        *,
        shape: DatasetShape = DatasetShape.v1,
        **kwargs: object,
    ) -> AsyncIterator[DatasetResponse | DatasetResponseV2 | DatasetSearchHit]:
        """Walk every search hit, following cursors until exhausted.

        Accepts the same keyword arguments as `search()`, except `cursor`,
        which this method manages.
        """
        if "cursor" in kwargs:
            raise CatalogUsageError("iter_search() manages the cursor; do not pass one")
        cursor: str | None = None
        while True:
            page = await self.search(cursor=cursor, shape=shape, **kwargs)  # type: ignore[call-overload]
            for result in page.results:
                yield result
            following = _next_cursor(page.next_cursor, cursor, len(page.results))
            if following is None:
                return
            cursor = following

    @overload
    async def resolve(
        self,
        uri: str,
        *,
        scope: LocationScope = ...,
        storage_platform: StoragePlatform | None = ...,
        cursor: str | None = ...,
        limit: int = ...,
        shape: Literal[DatasetShape.v1] = ...,
        instance: InstanceView | None = ...,
        root_uri: str | None = ...,
    ) -> DatasetSearchResponse[DatasetResponse]: ...

    @overload
    async def resolve(
        self,
        uri: str,
        *,
        scope: LocationScope = ...,
        storage_platform: StoragePlatform | None = ...,
        cursor: str | None = ...,
        limit: int = ...,
        shape: Literal[DatasetShape.v2],
        instance: InstanceView | None = ...,
        root_uri: str | None = ...,
    ) -> DatasetSearchResponse[DatasetResponseV2]: ...

    async def resolve(
        self,
        uri: str,
        *,
        scope: LocationScope = LocationScope.exact,
        storage_platform: StoragePlatform | None = None,
        cursor: str | None = None,
        limit: int = 50,
        shape: DatasetShape = DatasetShape.v1,
        instance: InstanceView | None = None,
        root_uri: str | None = None,
    ) -> (
        DatasetSearchResponse[DatasetResponse]
        | DatasetSearchResponse[DatasetResponseV2]
    ):
        """Resolve a file or directory URI to the dataset(s) registered at it.

        By default the match is the URI itself. `scope=ancestor` walks *up*,
        so a deep object key finds the dataset registered on a parent
        directory, closest match first; `scope=descendant` walks *down* and
        comes back in `id` order, since no match there outranks another.

        Pass `storage_platform` whenever the URI is a bare POSIX path: every
        HPC cluster mounts its own `/hpc/projects/x`, so without it the path
        resolves across all of them.

        Pages by cursor only. Keep `uri`, `scope` and `storage_platform`
        identical for the whole walk, or use `iter_resolve()`, which manages
        the cursor for you.

        Each record carries the instances the URI matched through, unless
        `instance` says otherwise; `shape=DatasetShape.v2` returns
        `DatasetResponseV2`.

        A deployment predating this route answers `NotFoundError: Dataset
        'resolve' not found` — the path falls through to the by-id route.
        That is a missing endpoint, not an unregistered URI.
        """
        params = _build_resolve_params(uri, scope, storage_platform, cursor, limit)
        params.update(
            _build_view_params(
                shape, instance, root_uri, storage_platform, send_platform=False
            )
        )
        response = await self._get(f"{_PREFIX}/resolve", params=params)
        return _resolve_page_model(DatasetShape(shape)).model_validate(response.json())

    @overload
    def iter_resolve(
        self,
        uri: str,
        *,
        scope: LocationScope = ...,
        storage_platform: StoragePlatform | None = ...,
        limit: int = ...,
        shape: Literal[DatasetShape.v1] = ...,
        instance: InstanceView | None = ...,
        root_uri: str | None = ...,
    ) -> AsyncIterator[DatasetResponse]: ...

    @overload
    def iter_resolve(
        self,
        uri: str,
        *,
        scope: LocationScope = ...,
        storage_platform: StoragePlatform | None = ...,
        limit: int = ...,
        shape: Literal[DatasetShape.v2],
        instance: InstanceView | None = ...,
        root_uri: str | None = ...,
    ) -> AsyncIterator[DatasetResponseV2]: ...

    async def iter_resolve(
        self,
        uri: str,
        *,
        scope: LocationScope = LocationScope.exact,
        storage_platform: StoragePlatform | None = None,
        limit: int = 50,
        shape: DatasetShape = DatasetShape.v1,
        instance: InstanceView | None = None,
        root_uri: str | None = None,
    ) -> AsyncIterator[DatasetResponse | DatasetResponseV2]:
        """Walk every dataset the URI resolves to, following cursors until exhausted."""
        cursor: str | None = None
        while True:
            page = await self.resolve(  # type: ignore[call-overload]
                uri,
                scope=scope,
                storage_platform=storage_platform,
                cursor=cursor,
                limit=limit,
                shape=shape,
                instance=instance,
                root_uri=root_uri,
            )
            for result in page.results:
                yield result
            following = _next_cursor(page.next_cursor, cursor, len(page.results))
            if following is None:
                return
            cursor = following

    async def copy(
        self,
        dataset_id: str,
        request: DatasetCopyRequest,
        *,
        copy_type: CopyType,
    ) -> DatasetCopyResponse:
        """Register the catalog side of a completed transfer of `dataset_id`.

        `copy_type` is required — the catalog never infers it from the
        destination or the body. A `fork` becomes a dataset of its own,
        written in one transaction with the `copy_of` edge tying it to the
        source (`lineage_edge_id` on the response). A `mirror` becomes
        another instance of the same dataset, with no edge (`instance_id`
        on the response); its identity fields must equal the source's.

        Replaying is safe: the destination identity is the idempotency key,
        so a replay returns the same ids and writes nothing, whatever its
        entries now say. Correct a fork with `update()` and a mirror with
        `update_instance()`, not by replaying with changed entries.

        A refusal raises `CopyError`, whose `code` says why and whose
        `retryable` says whether retrying the same request can help.
        """
        response = await self._post(
            f"{_PREFIX}/{dataset_id}/copy",
            params={"copy_type": copy_type.value},
            # exclude_none: lineage_metadata is stored untouched, so a null
            # the caller never set would be stored as one.
            json=request.model_dump(mode="json", exclude_none=True),
        )
        return DatasetCopyResponse.model_validate(response.json())

    async def list_instances(
        self,
        dataset_id: str,
        *,
        storage_platform: StoragePlatform | None = None,
        is_primary: bool | None = None,
        include_tombstoned: bool = False,
    ) -> DatasetInstanceListResponse:
        """Every copy of a dataset's bytes, primary first, each with its assets.

        Not paginated. Pass `include_tombstoned=True` when tracing where a
        copy came from: `copied_from_instance_id` keeps pointing at an
        instance after it is removed.
        """
        params = _build_instance_list_params(
            storage_platform, is_primary, include_tombstoned
        )
        response = await self._get(f"{_PREFIX}/{dataset_id}/instances", params=params)
        return DatasetInstanceListResponse.model_validate(response.json())

    async def get_instance(
        self, dataset_id: str, instance_id: str
    ) -> DatasetInstanceWithLocationsResponse:
        response = await self._get(f"{_PREFIX}/{dataset_id}/instances/{instance_id}")
        return DatasetInstanceWithLocationsResponse.model_validate(response.json())

    async def update_instance(
        self, dataset_id: str, instance_id: str, update: DatasetInstanceUpdate
    ) -> DatasetInstanceWithLocationsResponse:
        """Fill in a partial mirror or fix a copy in place.

        Locations are matched by `location_uri`; omitted assets stay — remove
        one with `delete_instance_asset()`.
        """
        response = await self._patch(
            f"{_PREFIX}/{dataset_id}/instances/{instance_id}",
            json=update.model_dump(mode="json", exclude_unset=True),
        )
        return DatasetInstanceWithLocationsResponse.model_validate(response.json())

    async def delete_instance(self, dataset_id: str, instance_id: str) -> None:
        """Tombstone one copy and its assets.

        The server refuses the primary with HTTP 409: promote another
        instance first, or delete the dataset.
        """
        await self._delete(f"{_PREFIX}/{dataset_id}/instances/{instance_id}")

    async def promote_instance(
        self, dataset_id: str, instance_id: str
    ) -> DatasetInstanceResponse:
        """Make this instance the authoritative copy, demoting the current primary."""
        response = await self._post(
            f"{_PREFIX}/{dataset_id}/instances/{instance_id}/promote"
        )
        return DatasetInstanceResponse.model_validate(response.json())

    async def delete_instance_asset(
        self, dataset_id: str, instance_id: str, asset_id: str
    ) -> None:
        """Tombstone one asset of one copy.

        The server refuses an instance's last live asset with HTTP 409.
        Removing a primary asset does not cascade to the mirrors.
        """
        await self._delete(
            f"{_PREFIX}/{dataset_id}/instances/{instance_id}/assets/{asset_id}"
        )

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
        response = await self.list(
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

    @overload
    async def get(
        self,
        ref: str | DatasetRef,
        *,
        exclude_tombstoned: bool = ...,
        include_lineage: bool = ...,
        include_collections: bool = ...,
        shape: Literal[DatasetShape.v1] = ...,
        instance: InstanceView | None = ...,
        storage_platform: StoragePlatform | None = ...,
        root_uri: str | None = ...,
    ) -> DatasetWithRelationsResponse: ...

    @overload
    async def get(
        self,
        ref: str | DatasetRef,
        *,
        exclude_tombstoned: bool = ...,
        include_lineage: bool = ...,
        include_collections: bool = ...,
        shape: Literal[DatasetShape.v2],
        instance: InstanceView | None = ...,
        storage_platform: StoragePlatform | None = ...,
        root_uri: str | None = ...,
    ) -> DatasetWithRelationsResponseV2: ...

    async def get(
        self,
        ref: str | DatasetRef,
        *,
        exclude_tombstoned: bool = True,
        include_lineage: bool = False,
        include_collections: bool = False,
        shape: DatasetShape = DatasetShape.v1,
        instance: InstanceView | None = None,
        storage_platform: StoragePlatform | None = None,
        root_uri: str | None = None,
    ) -> DatasetWithRelationsResponse | DatasetWithRelationsResponseV2:
        """Fetch one dataset.

        `shape=DatasetShape.v2` returns `DatasetWithRelationsResponseV2`,
        which drops the flat `locations`. `instance` picks which copies the
        record carries; `storage_platform` and `root_uri` need
        `instance=InstanceView.filter`.
        """
        params = _build_view_params(
            shape, instance, root_uri, storage_platform, send_platform=True
        )
        dataset_id = ref if isinstance(ref, str) else await self._resolve(ref)
        if not exclude_tombstoned:
            params["exclude_tombstoned"] = False
        if include_lineage:
            params["include_lineage"] = True
        if include_collections:
            params["include_collections"] = True
        response = await self._get(f"{_PREFIX}/{dataset_id}", params=params)
        return _dataset_with_relations_model(DatasetShape(shape)).model_validate(
            response.json()
        )

    @overload
    async def create(
        self,
        dataset: DatasetRequest,
        *,
        shape: Literal[DatasetShape.v1] = ...,
    ) -> DatasetResponse: ...

    @overload
    async def create(
        self,
        dataset: DatasetRequest,
        *,
        shape: Literal[DatasetShape.v2],
    ) -> DatasetResponseV2: ...

    async def create(
        self,
        dataset: DatasetRequest,
        *,
        shape: DatasetShape = DatasetShape.v1,
    ) -> DatasetResponse | DatasetResponseV2:
        response = await self._post(
            f"{_PREFIX}/",
            params=_shape_params(shape),
            json=dataset.model_dump(mode="json"),
        )
        return _dataset_model(DatasetShape(shape)).model_validate(response.json())

    @overload
    async def update(
        self,
        ref: str | DatasetRef,
        dataset: DatasetRequest,
        *,
        shape: Literal[DatasetShape.v1] = ...,
    ) -> DatasetResponse: ...

    @overload
    async def update(
        self,
        ref: str | DatasetRef,
        dataset: DatasetRequest,
        *,
        shape: Literal[DatasetShape.v2],
    ) -> DatasetResponseV2: ...

    async def update(
        self,
        ref: str | DatasetRef,
        dataset: DatasetRequest,
        *,
        shape: DatasetShape = DatasetShape.v1,
    ) -> DatasetResponse | DatasetResponseV2:
        dataset_id = ref if isinstance(ref, str) else await self._resolve(ref)
        response = await self._patch(
            f"{_PREFIX}/{dataset_id}",
            params=_shape_params(shape),
            json=dataset.model_dump(mode="json", exclude_unset=True),
        )
        return _dataset_model(DatasetShape(shape)).model_validate(response.json())

    async def delete(self, ref: str | DatasetRef) -> None:
        dataset_id = ref if isinstance(ref, str) else await self._resolve(ref)
        await self._delete(f"{_PREFIX}/{dataset_id}")
