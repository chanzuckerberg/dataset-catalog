# DataFrames

Pull catalog datasets into a flat table, **one row per dataset**.

```bash
uv pip install 'catalog-client[dataframe]'
```

```python
from catalog_client import CatalogClient, to_dataframe

with CatalogClient(base_url=..., api_token=...) as client:
    df = to_dataframe(client, project="my-project")
```

For one row per *asset* — checksums, URIs, sizes — use
[`generate_manifest`](../manifest/README.md) instead.

## Route selection

The route is picked from the filters you pass; you never choose it directly.

| Filters used | Route | Notes |
|---|---|---|
| `project`, `modality`, `version`, `access_scope`, `is_latest`, or none | `datasets.list()` | Cursor-walked via `iter_all()`. Records are complete. |
| any of `q`, `organism`, `tissue`, `sub_modality`, `assay`, `disease`, `development_stage`, `cohort`, `file_format`, `storage_platform` | `datasets.search(hydrate=True)` | Hydration costs one extra query per page and caps `page_size` at 100. |

Both routes return full dataset records, so the same columns are available either way.

Two consequences worth knowing:

- **`version` on the search route is filtered client-side.** The search index does
  not support it, so matching rows are fetched and then dropped. Correct, but it
  reads more than it returns.
- **`sort=relevance` and `sort=alphabetical` only exist on the search route.**
  Asking for one when your filters resolve to the list route raises
  `CatalogUsageError` rather than silently ignoring it.

`canonical_id` is deliberately not a filter here. To pull the versions of one
dataset, use `client.datasets.list(canonical_id=...)`, or filter the frame on the
`canonical_id` column.

## Columns

`DEFAULT_COLUMNS` covers dataset identity, modality, the common ontology labels,
and governance:

```
id  canonical_id  version  name  project  modality  dataset_type  is_latest
organism  tissue  disease  sub_modality  access_scope  license
created_at  last_modified_at
```

Pass `columns` to choose your own. Entries are dot-paths, or `ColumnSpec` when you
want to name the output column:

```python
from catalog_client import ColumnSpec, DEFAULT_COLUMNS, to_dataframe

df = to_dataframe(
    client,
    project="my-project",
    columns=[
        "canonical_id",
        "name",
        ColumnSpec("metadata.data_summary.cell_count", alias="cells"),
    ],
)
```

`rename` is applied last and maps output name to final name, so you can rename a
default column without respecifying the list:

```python
to_dataframe(client, project="p", rename={"canonical_id": "dataset"})
```

### Path syntax

Paths are rooted at the dataset record, so metadata paths carry the `metadata.`
prefix. A missing key anywhere returns `None` rather than raising.

| Syntax | Example | Result |
|---|---|---|
| plain key | `governance.license` | `"MIT"` |
| `[]` list expansion | `metadata.sample.organism[].label` | `"Homo sapiens; Mus musculus"` |
| deep chain through a list | `metadata.data_summary.channels[].biological_annotation.marker` | `"DAPI; GFP"` |
| integer index | `metadata.data_summary.dimension.0` | `512` |

List values are joined with `list_sep` (default `"; "`). Pass `list_sep=None` to
keep native Python lists in the cells.

If a requested column is `None` in every row, a `UserWarning` names it — that
almost always means a typo in the path.

### Computed columns

Two names are resolved by a function rather than a path. They are **not** in the
defaults; ask for them explicitly:

```python
to_dataframe(client, columns=[*DEFAULT_COLUMNS, "asset_count", "total_size_bytes"])
```

| Name | Value |
|---|---|
| `asset_count` | number of entries in `locations` |
| `total_size_bytes` | sum of `size_bytes` across `locations`, or `None` if none report one |

## Custom mappers

When the path syntax is not enough, pass a `mapper` — a callable that receives the
**Pydantic model** and returns a dict:

```python
def enrich(ds):
    if ds.tombstoned:
        return None                        # drop the row
    summary = ds.metadata.data_summary
    return {
        "n_channels": len(summary.channels or []) if summary else 0,
        "label": f"{ds.canonical_id} v{ds.version}",
    }

df = to_dataframe(client, project="my-project", mapper=enrich)
```

The contract:

- Output is **merged over** the declarative columns — it adds and overrides, so
  you can extend the defaults with one derived field. Pass `columns=[]` for a
  mapper-only frame.
- Returning `None` **drops the row**, which is how you express a filter the API
  cannot.
- Mapper values pass through **unchanged** — no `list_sep` joining, no enum
  unwrapping. You built the value deliberately.
- Which model arrives depends on the route (`DatasetResponse` from search,
  `DatasetWithRelationsResponse` from list), so do not assume the relations
  fields are populated.
- If your mapper raises, the error is re-raised as `CatalogUsageError` naming the
  dataset id. Every metadata submodel is optional, so guard against `None` —
  `ds.metadata.data_summary.channels` will bite otherwise.

Row assembly order is fixed: **columns → mapper → rename**.

## Without pandas

`iter_records()` takes the same arguments and yields plain dicts, streaming page
by page. Use it to avoid the dependency, drive a progress bar, or feed a
different tabular library:

```python
from catalog_client import iter_records

for row in iter_records(client, project="my-project", limit=1000):
    ...
```

## Paging and limits

- `limit` caps the rows returned; `None` (the default) walks every match.
  `itertools.islice` stops the walk, so a small `limit` costs one page.
- `page_size` is records per request. Capped at 100 on the search route and 500
  on the list route, with a warning if you exceed it.
- Both routes page by cursor, so deep result sets are fine.
