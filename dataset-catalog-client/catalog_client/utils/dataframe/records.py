"""Flat dataset records, one dict per dataset — the pandas-free layer."""

from __future__ import annotations

import itertools
import os
import sys
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
from catalog_client.utils.dataframe._route import MAX_PAGE_SIZE, iter_datasets
from catalog_client.utils.dataframe._types import ColumnSpec, RecordMapper

if TYPE_CHECKING:
    from types import FrameType

    from catalog_client.client.catalog import CatalogClient

_PACKAGE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
"""The ``catalog_client`` directory, used to tell our frames from the caller's."""


def _caller_stacklevel() -> int:
    """The ``stacklevel`` that names the first frame outside ``catalog_client``.

    Python 3.12 added ``warnings.warn(skip_file_prefixes=...)`` for exactly
    this; the package floor is 3.11, so walk the stack instead.

    A fixed ``stacklevel`` cannot work here.  Warnings are raised from two
    different depths — eagerly from ``iter_records``, and from inside the row
    generator, whose stack at resumption time belongs to whoever consumed it
    rather than to whoever built it.  Asking the interpreter how deep we
    actually are keeps attribution correct through both, and through
    ``to_dataframe`` calling ``iter_records`` on the way.

    Call this from the same function that calls :func:`warnings.warn`.
    """
    level = 1
    frame: FrameType | None = sys._getframe(1)
    while frame is not None and frame.f_code.co_filename.startswith(_PACKAGE_DIR):
        level += 1
        frame = frame.f_back
    return level


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
    page_size: int = MAX_PAGE_SIZE,
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
        sort: Sort order.  Left to the server when ``None``, as in
            ``datasets.iter_all()`` and ``datasets.search()``.  ``relevance``
            and ``alphabetical`` exist only on the search route; asking for
            one when the filters resolve to the list route raises
            :class:`~catalog_client.CatalogUsageError`.  See the package
            README on walk stability before paging through a large result.
        limit: Maximum rows to yield.  ``None`` walks every match.
        page_size: Records fetched per request.  Capped at 100 on both routes,
            with a warning, since the route is chosen from the filters rather
            than by you.

    Returns:
        An iterator of one ``dict`` per dataset, keyed by resolved column name.

    Raises:
        CatalogUsageError: For an invalid ``limit``, ``page_size``, or
            ``columns``, a ``sort`` the chosen route does not support, or a
            *mapper* that raises.
    """
    # Deliberately not a generator function: the checks below have to run on
    # this call rather than on the first `next()`, so a bad argument is raised
    # from the caller's line instead of from wherever the rows get consumed.
    specs, page_size = _validate(columns, mapper, limit, page_size)

    return _iter_rows(
        client,
        filters={
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
        },
        specs=specs,
        mapper=mapper,
        rename=rename,
        list_sep=list_sep,
        exclude_tombstoned=exclude_tombstoned,
        sort=sort,
        limit=limit,
        page_size=page_size,
    )


def _validate(
    columns: Sequence[str | ColumnSpec] | None,
    mapper: RecordMapper | None,
    limit: int | None,
    page_size: int,
) -> tuple[list[ColumnSpec], int]:
    """Check the shaping arguments and resolve the columns."""
    if limit is not None and limit < 0:
        raise CatalogUsageError(f"limit must be >= 0, got {limit}")

    if page_size < 1:
        raise CatalogUsageError(f"page_size must be >= 1, got {page_size}")
    if page_size > MAX_PAGE_SIZE:
        warnings.warn(
            f"page_size={page_size} exceeds the maximum of {MAX_PAGE_SIZE}; "
            f"capping at {MAX_PAGE_SIZE}.",
            UserWarning,
            stacklevel=_caller_stacklevel(),
        )
        page_size = MAX_PAGE_SIZE

    specs = resolve_columns(columns)
    if not specs and mapper is None:
        raise CatalogUsageError(
            "columns is empty and no mapper was given, so every row would be "
            "empty. Pass columns, a mapper, or leave columns as None for the "
            "defaults."
        )
    return specs, page_size


def _iter_rows(
    client: CatalogClient,
    *,
    filters: dict[str, Any],
    specs: list[ColumnSpec],
    mapper: RecordMapper | None,
    rename: Mapping[str, str] | None,
    list_sep: str | None,
    exclude_tombstoned: bool,
    sort: DatasetSortOption | DatasetListSortOption | None,
    limit: int | None,
    page_size: int,
) -> Iterator[dict[str, Any]]:
    """Walk the chosen route and flatten each record, one row at a time.

    Arguments are assumed already validated by :func:`_validate`.
    """
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
    # Resolved once here rather than per column: this frame is the reference
    # point, and every warning below is raised from it.
    stacklevel = _caller_stacklevel()
    for spec in specs:
        name = spec.column_name
        if rename:
            name = rename.get(name, name)
        if name not in seen_non_null:
            warnings.warn(
                f"Column {spec.path!r} (output {name!r}) resolved to None for "
                "every row. Verify the path syntax and metadata schema.",
                UserWarning,
                stacklevel=stacklevel,
            )
