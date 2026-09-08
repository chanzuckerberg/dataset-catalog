"""Pick between the list route and the hydrated search route."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Iterator

from catalog_client.exceptions import CatalogUsageError
from catalog_client.models.dataset import (
    DatasetListSortOption,
    DatasetSortOption,
)

if TYPE_CHECKING:
    from catalog_client.client.catalog import CatalogClient
    from catalog_client.models.dataset import (
        DatasetResponse,
        DatasetWithRelationsResponse,
    )

SEARCH_ONLY_FILTERS = (
    "q",
    "organism",
    "tissue",
    "sub_modality",
    "assay",
    "disease",
    "development_stage",
    "cohort",
    "file_format",
    "storage_platform",
)
"""Filters the search index supports and the list route does not."""

LIST_ONLY_FILTERS = ("version",)
"""Filters the list route supports and the search index does not."""

SHARED_FILTERS = ("modality", "project", "is_latest", "access_scope")
"""Filters both routes accept, passed straight through either way."""

_HYDRATED_MAX_PAGE_SIZE = 100
_LIST_MAX_PAGE_SIZE = 500


def _clamp_page_size(page_size: int, maximum: int, route: str) -> int:
    if page_size > maximum:
        warnings.warn(
            f"page_size={page_size} exceeds the maximum of {maximum} for the "
            f"{route} route; capping at {maximum}.",
            UserWarning,
            stacklevel=4,
        )
        return maximum
    if page_size < 1:
        raise CatalogUsageError(f"page_size must be >= 1, got {page_size}")
    return page_size


def _search_sort(
    sort: DatasetSortOption | DatasetListSortOption | None,
) -> DatasetSortOption | None:
    """Widen a list sort option to its search equivalent."""
    if sort is None:
        return None
    return DatasetSortOption(sort.value)


def _list_sort(
    sort: DatasetSortOption | DatasetListSortOption | None,
) -> DatasetListSortOption | None:
    """Narrow a search sort option, rejecting the ones the list route lacks."""
    if sort is None:
        return None
    try:
        return DatasetListSortOption(sort.value)
    except ValueError:
        raise CatalogUsageError(
            f"sort={sort.value!r} is only supported by the search route, but "
            "these filters resolve to the list route. Use one of "
            f"{[option.value for option in DatasetListSortOption]}, or add a "
            "search-only filter."
        ) from None


def iter_datasets(
    client: CatalogClient,
    filters: dict[str, Any],
    *,
    exclude_tombstoned: bool,
    sort: DatasetSortOption | DatasetListSortOption | None,
    page_size: int,
) -> Iterator[DatasetResponse | DatasetWithRelationsResponse]:
    """Yield full dataset records for *filters*, choosing the cheaper route.

    Any search-only filter routes to ``datasets.search(hydrate=True)``, which
    returns full ``DatasetResponse`` records rather than the lightweight hits
    the search route yields by default.  Otherwise ``datasets.iter_all()``
    walks the list route, whose records are already complete.

    Filters that only the list route understands are applied client-side when
    the search route is chosen, so a mixed query still returns correct rows —
    at the cost of fetching the ones that get dropped.
    """
    search_filters = {
        name: value for name in SEARCH_ONLY_FILTERS if (value := filters.get(name))
    }

    if not search_filters:
        page_size = _clamp_page_size(page_size, _LIST_MAX_PAGE_SIZE, "list")
        yield from client.datasets.iter_all(
            version=filters.get("version"),
            modality=filters.get("modality"),
            project=filters.get("project"),
            access_scope=filters.get("access_scope"),
            is_latest=filters.get("is_latest"),
            exclude_tombstoned=exclude_tombstoned,
            sort=_list_sort(sort),
            limit=page_size,
        )
        return

    page_size = _clamp_page_size(page_size, _HYDRATED_MAX_PAGE_SIZE, "search")
    residual = {
        name: value for name in LIST_ONLY_FILTERS if (value := filters.get(name))
    }
    shared = {name: filters.get(name) for name in SHARED_FILTERS}
    # iter_search takes **kwargs, so the filters go in as a mapping rather
    # than being spelled out the way iter_all's typed signature requires.
    hits = client.datasets.iter_search(
        hydrate=True,
        sort=_search_sort(sort),
        limit=page_size,
        **search_filters,
        **shared,
    )
    for hit in hits:
        # Search has no tombstone filter, so honour it here to keep both
        # routes' output consistent.
        if exclude_tombstoned and getattr(hit, "tombstoned", False):
            continue
        if any(getattr(hit, name, None) != value for name, value in residual.items()):
            continue
        yield hit  # type: ignore[misc]
