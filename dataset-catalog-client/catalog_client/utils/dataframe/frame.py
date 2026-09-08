"""Pull catalog datasets into a pandas DataFrame."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Sequence

from catalog_client.exceptions import CatalogUsageError
from catalog_client.models.dataset import (
    DatasetListSortOption,
    DatasetModality,
    DatasetSortOption,
)
from catalog_client.utils.dataframe._columns import resolve_columns
from catalog_client.utils.dataframe._types import ColumnSpec, RecordMapper
from catalog_client.utils.dataframe.records import iter_records

if TYPE_CHECKING:
    import pandas

    from catalog_client.client.catalog import CatalogClient


def _import_pandas() -> Any:
    """Import pandas on demand, since it is an optional extra."""
    try:
        import pandas
    except ImportError as exc:
        raise CatalogUsageError(
            "to_dataframe() requires pandas, which is an optional dependency. "
            "Install it with: uv pip install 'catalog-client[dataframe]'. "
            "To avoid the dependency, use iter_records() and build the table "
            "yourself."
        ) from exc
    return pandas


def to_dataframe(
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
) -> pandas.DataFrame:
    """Pull matching datasets into a DataFrame, one row per dataset.

    The route is chosen from the filters: any search-index filter (``q``,
    ``organism``, ``tissue``, ``assay``, …) uses
    ``datasets.search(hydrate=True)``; otherwise ``datasets.list()`` is walked.
    Either way the records are complete, so the same columns are available.

    Takes the same arguments as
    :func:`~catalog_client.utils.dataframe.iter_records`, which see for the
    full reference.

    Requires the ``dataframe`` extra::

        uv pip install 'catalog-client[dataframe]'

    Examples::

        # every dataset in a project, default columns
        df = to_dataframe(client, project="my-project")

        # search route, custom columns and a renamed default
        df = to_dataframe(
            client,
            organism="Homo sapiens",
            columns=["canonical_id", "name",
                     ColumnSpec("metadata.data_summary.cell_count", alias="cells")],
            rename={"canonical_id": "dataset"},
        )

    Returns:
        A :class:`pandas.DataFrame`.  Columns follow the requested order, with
        any mapper-only columns appended.  An empty result still carries the
        declarative columns, so downstream code can index them safely.

    Raises:
        CatalogUsageError: If pandas is not installed, or for the argument
            errors documented on :func:`iter_records`.
    """
    pandas = _import_pandas()

    rows = list(
        iter_records(
            client,
            q=q,
            version=version,
            modality=modality,
            project=project,
            access_scope=access_scope,
            is_latest=is_latest,
            organism=organism,
            tissue=tissue,
            sub_modality=sub_modality,
            assay=assay,
            disease=disease,
            development_stage=development_stage,
            cohort=cohort,
            file_format=file_format,
            storage_platform=storage_platform,
            columns=columns,
            mapper=mapper,
            rename=rename,
            list_sep=list_sep,
            exclude_tombstoned=exclude_tombstoned,
            sort=sort,
            limit=limit,
            page_size=page_size,
        )
    )

    if rows:
        return pandas.DataFrame(rows)

    # With no rows pandas cannot infer the schema, so state it. Only the
    # declarative columns are knowable here — a mapper never ran.
    names = []
    for spec in resolve_columns(columns):
        name = spec.column_name
        names.append(rename.get(name, name) if rename else name)
    return pandas.DataFrame(columns=names)
