"""Flat dataset records, one dict per dataset — the pandas-free layer."""

from __future__ import annotations

import itertools
import warnings
from typing import TYPE_CHECKING, Any, Iterator, Mapping, Sequence

from catalog_client.exceptions import CatalogUsageError
from catalog_client.models.dataset import (
    DatasetListSortOption,
    DatasetModality,
    DatasetSortOption,
)
from catalog_client.utils.dataframe._columns import resolve_columns
from catalog_client.utils.dataframe._flatten import flatten_record
from catalog_client.utils.dataframe._route import iter_datasets
from catalog_client.utils.dataframe._types import ColumnSpec, RecordMapper

if TYPE_CHECKING:
    from catalog_client.client.catalog import CatalogClient


def iter_records(
    client: CatalogClient,
    *,
    # Filters — names match datasets.list() / datasets.search() exactly.
    q: str | None = None,
    version: str | None = None,
    modality: DatasetModality | None = None,
    project: str | None = None,
    access_scope: str | None = None,
    is_latest: bool | None = None,
    organism: str | None = None,
    tissue: str | None = None,
    sub_modality: str | None = None,
    assay: str | None = None,
    disease: str | None = None,
    development_stage: str | None = None,
    cohort: str | None = None,
    file_format: str | None = None,
    storage_platform: str | None = None,
    # Shaping.
    columns: Sequence[str | ColumnSpec] | None = None,
    mapper: RecordMapper | None = None,
    rename: Mapping[str, str] | None = None,
    list_sep: str | None = "; ",
    exclude_tombstoned: bool = True,
    sort: DatasetSortOption | DatasetListSortOption | None = None,
    limit: int | None = None,
    page_size: int = 100,
) -> Iterator[dict[str, Any]]:
    """Yield one flat dict per matching dataset, streaming page by page.

    This is what :func:`~catalog_client.utils.dataframe.to_dataframe` is built
    on.  Use it directly to avoid the pandas dependency, to process rows as
    they arrive, or to feed a different tabular library.

    Args:
        client: An authenticated :class:`~catalog_client.CatalogClient`.
        q: Free-text query.  Note that a multi-word ``q`` is OR-tokenized by
            the server, which widens recall.
        version, modality, project, access_scope, is_latest: Filters both
            routes accept, except ``version``, which only the list route
            supports and which is applied client-side on the search route.
        organism, tissue, sub_modality, assay, disease, development_stage,
            cohort, file_format, storage_platform: Search-index filters.
            Passing any of these routes the query through
            ``datasets.search(hydrate=True)`` instead of ``datasets.list()``.
        columns: Columns to extract, as dot-paths or
            :class:`~catalog_client.utils.dataframe.ColumnSpec`.  Defaults to
            :data:`~catalog_client.utils.dataframe.DEFAULT_COLUMNS`.  Pass an
            empty sequence for a mapper-only row.
        mapper: Optional
            :data:`~catalog_client.utils.dataframe.RecordMapper` merged over
            the extracted columns.  Return ``None`` from it to drop a row.
        rename: Applied last, mapping resolved column name to final name.  Use
            it to rename a default column without respecifying the whole list.
        list_sep: Separator used to join list values into one cell.  Pass
            ``None`` to keep native Python lists.  Does not apply to mapper
            output.
        exclude_tombstoned: Skip soft-deleted datasets (default ``True``).
        sort: Sort order.  ``relevance`` and ``alphabetical`` exist only on the
            search route; asking for one when the filters resolve to the list
            route raises :class:`~catalog_client.CatalogUsageError`.
        limit: Maximum rows to yield.  ``None`` walks every match.
        page_size: Records fetched per request.  Capped at 100 on the search
            route and 500 on the list route, with a warning.

    Yields:
        One ``dict`` per dataset, keyed by resolved column name.

    Raises:
        CatalogUsageError: For an invalid ``page_size``, a ``sort`` the chosen
            route does not support, or a *mapper* that raises.
    """
    if limit is not None and limit < 0:
        raise CatalogUsageError(f"limit must be >= 0, got {limit}")

    specs = resolve_columns(columns)
    if not specs and mapper is None:
        raise CatalogUsageError(
            "columns is empty and no mapper was given, so every row would be "
            "empty. Pass columns, a mapper, or leave columns as None for the "
            "defaults."
        )

    filters = {
        "q": q,
        "version": version,
        "modality": modality,
        "project": project,
        "access_scope": access_scope,
        "is_latest": is_latest,
        "organism": organism,
        "tissue": tissue,
        "sub_modality": sub_modality,
        "assay": assay,
        "disease": disease,
        "development_stage": development_stage,
        "cohort": cohort,
        "file_format": file_format,
        "storage_platform": storage_platform,
    }

    records = iter_datasets(
        client,
        filters,
        exclude_tombstoned=exclude_tombstoned,
        sort=sort,
        page_size=page_size,
    )

    emitted = 0
    seen_non_null: set[str] = set()
    for record in itertools.islice(records, limit):
        row = flatten_record(
            record,
            specs,
            mapper=mapper,
            list_sep=list_sep,
            rename=rename,
        )
        if row is None:
            continue
        emitted += 1
        seen_non_null.update(key for key, value in row.items() if value is not None)
        yield row

    if emitted:
        _warn_empty_columns(specs, rename, seen_non_null)


def _warn_empty_columns(
    specs: list[ColumnSpec],
    rename: Mapping[str, str] | None,
    seen_non_null: set[str],
) -> None:
    """Flag declarative columns that were None in every row — usually a typo.

    Mapper-produced columns are excluded: an always-None mapper column may
    well be intentional.
    """
    for spec in specs:
        name = spec.column_name
        if rename:
            name = rename.get(name, name)
        if name not in seen_non_null:
            warnings.warn(
                f"Column {spec.path!r} (output {name!r}) resolved to None for "
                "every row. Verify the path syntax and metadata schema.",
                UserWarning,
                stacklevel=3,
            )
