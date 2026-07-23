# REST API Calls: Catalog Reads and OLS expansion

Use this reference when you need REST Catalog API access, or manual ontology expansion.

For ordinary reads, use Python’s standard-library REST path. It requires no installation. The `catalog` CLI and `catalog_client` SDK provide optional conveniences such as pagination, fan-out, result union, and typed post-processing.

## Direct REST

All API paths begin with `/api/` and use the `X-catalog-api-token` header. Never put the token in a URL or command-line argument.

```python
import json, os, urllib.parse, urllib.request
BASE = (os.environ.get("CATALOG_API_URL") or "https://datacatalog.prod-sci-data.prod.czi.team").rstrip("/")
H = {"X-catalog-api-token": os.environ["CATALOG_API_TOKEN"]}
q = urllib.parse.urlencode({"q": "liver", "limit": 10})
with urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/datasets/search/?{q}", headers=H)) as r:
    data = json.load(r)
```

## Read endpoints

List-style responses have this shape: `{total, limit, offset, results:[…]}`.
Search also returns `facets`.

| Path                                | Purpose                                    |
| ----------------------------------- | ------------------------------------------ |
| `GET /api/datasets/search/`         | Free-text dataset search                   |
| `GET /api/datasets/`                | List datasets or apply exact-match filters |
| `GET /api/datasets/{id}`            | Fetch one full dataset record              |
| `GET /api/collections/`             | List collections                           |
| `GET /api/collections/{id}`         | Fetch one collection                       |
| `GET /api/collections/{id}/entries` | Fetch child membership                     |
| `GET /api/collections/{id}/parents` | Fetch parent membership                    |
| `GET /api/lineage/`                 | List lineage edges                         |
| `GET /api/lineage/{edge_id}`        | Fetch one lineage edge                     |

`/api/datasets/{id}` requires the dataset UUID, not its `canonical_id`. Resolve a canonical ID through the list route:

```
GET /api/datasets/?canonical_id=<value>
```

## Search or list?

### Free-text search

Use:

```
GET /api/datasets/search/
```

Supported parameters include:

* `q`
* `modality`
* `project`
* `is_latest`
* `access_scope`
* `organism`
* `tissue`
* `sub_modality`
* `assay`
* `disease`
* `development_stage`
* `sort`
* `facets`
* `offset`
* `limit`

`sort` may be:

```text
relevance
alphabetical
last_modified
newest
oldest
```

The default limit is 10.

Search returns lightweight hits containing fields such as:

```text
id, canonical_id, version, name, modality, dataset_type,
project, is_latest, access_scope, score
```

Search hits do not contain `locations`. Fetch the full record to inspect assets.

### Exact-match filtering

Use:

```text
GET /api/datasets/
```

Supported filters include:

* `canonical_id`
* `version`
* `modality`
* `project`
* `access_scope`
* `is_latest`

Additional controls include:

* `exclude_tombstoned`
* `include_lineage`
* `include_collections`
* `offset`
* `limit`

Text search does not work on this route. Do not use `search=` or `q=` here.

The list route may silently ignore unsupported parameters. Confirm that a filter works by checking that `total` changes.

## Facets

Facets are returned by the search endpoint. There is no `/api/datasets/facets/` or `/api/facets/` endpoint.

Pass each facet field as a repeated query parameter:

```text
facets=organism&facets=tissue&facets=assay
```

With `urllib`, pass a list and set `doseq=True`:


```python
import json, urllib.parse, urllib.request
qs = urllib.parse.urlencode({"facets": ["organism", "tissue", "assay"], "limit": 1}, doseq=True)
req = urllib.request.Request(f"{BASE}/api/datasets/search/?{qs}", headers=H)
with urllib.request.urlopen(req) as r:
    facets = json.load(r)["facets"]
```

Do not comma-join facet names:

```python
# Correct
facets=["tissue", "modality"]

# Incorrect
facets="tissue,modality"
```

Likely facet fields are:

| Field               | Notes                           |
| ------------------- | ------------------------------- |
| `modality`          | Confirmed                       |
| `organism`          | Confirmed                       |
| `dataset_type`      | Search facet, not a list filter |
| `tissue`            | Expected                        |
| `assay`             | Expected                        |
| `disease`           | Expected                        |
| `sub_modality`      | Expected                        |
| `development_stage` | Expected                        |
| `project`           | Expected                        |
| `access_scope`      | Expected                        |

The client does not validate facet names. Unsupported fields may simply be absent from the response, so verify each requested field empirically.

Facet buckets are capped to the top ~50 values. They do not provide a complete distinct-value list.

## Pagination and data cautions

* The maximum list-page size is 100.
* Use `offset` to retrieve subsequent pages.
* `limit > 100` returns HTTP 422.
* `/docs` and `/openapi.json` may require SSO; the API token may not be sufficient.
* Aggregate fields like `data_summary.cell_count` may be collection-level values repeated on every constituent datasets. Do not sum them blindly. Report per-dataset values or deduplicate canonical datasets first.

SDK pagination example:

```python
def iter_datasets(catalog, **filters):
    offset = 0
    while True:
        page = catalog.datasets.list(offset=offset, limit=100, **filters).results
        if not page:
            return
        yield from page
        offset += len(page)
```

## Dataset record shape

A full dataset record includes fields such as:

```text
id
canonical_id
version
project
name
description
modality
doi
dataset_type
is_latest
tombstoned
created_at
last_modified_at
```

It also includes:

```text
locations: [
  {
    location_uri,
    asset_type,
    description,
    size_bytes,
    checksum,
    file_format,
    storage_platform
  }
]

governance: {
  license,
  access_scope,
  is_pii,
  is_phi,
  data_owner,
  embargoed_until,
  ...
}

metadata: {
  experiment: {
    sub_modality,
    assay,
    ...
  },
  sample: {
    organism,
    tissue,
    disease,
    ...
  },
  data_summary: {
    cell_count,
    feature_count,
    channels,
    ...
  }
}
```

`incoming_lineage`, `outgoing_lineage`, and `collections` are populated when their corresponding include flags are enabled.

Allowed values include:

```text
modality: imaging | sequencing | mass spec | unknown
dataset_type: raw | processed
```

## OLS term expansion

Prefer the bundled `ols.py` handler for ontology expansion. It prints distilled term rows (no raw payload), needs no installation or token, and — being a plain subprocess — runs inside the `catalog-reader` subagent, which the `ols` MCP cannot reach.
`ols.py search <term> --ontology <uberon|cl|efo|mondo>` resolves the term to its label and synonyms; `children`/`descendants`/`ancestors` walk the hierarchy. `search_expanded.py --q <term>` wraps the same handler to expand, fan out, and union in one call, over the public OLS4 REST API.

Optional flags add hierarchy expansion:

```text
--children
--subtypes
--ancestors
```

Use the `ols` MCP only as a last resort — for a semantic-neighbor search (`searchWithEmbeddingModel` / `getSimilarClasses`) or a `fetch` that `ols.py` does not expose. It returns the full OLS payload into context and cannot run inside the `catalog-reader` subagent.

Expand terms agent-side, then search the Catalog once per term and union results by dataset `id`.

### OLS tools

| Tool                                             | Purpose                                                       |
| ------------------------------------------------ | ------------------------------------------------------------- |
| `search` / `searchClasses`                       | Resolve a term to ontology classes, labels, IDs, and synonyms |
| `fetch`                                          | Retrieve a class definition and complete synonym list         |
| `getChildren`                                    | Retrieve immediate subtypes                                   |
| `getDescendants`                                 | Retrieve the complete subtype hierarchy                       |
| `getAncestors`                                   | Retrieve broader parent terms                                 |
| `searchWithEmbeddingModel` / `getSimilarClasses` | Find semantic neighbors                                       |

Scope searches to an ontology such as `uberon`, `cl`, `efo`, or `mondo` when known.

### Expansion workflow

1. Search for the original term.
2. Collect its preferred label and useful synonyms.
3. Add children or descendants when subtype recall is needed.
4. Add ancestors only for highly specific starting terms.
5. Remove generic terms.
6. Search the Catalog separately for every retained term.
7. Union results by dataset `id`.
8. Tell the user which terms were searched.

When the client is installed:

```bash
scripts/search_expanded.py --terms "term1,term2,term3"
```

Without the client, call the search endpoint once per term using `urllib` and deduplicate by `id`.

### Precision rule

Catalog free-text queries are OR-tokenized. A query such as:

```text
red blood cell
```

may behave like:

```text
red OR blood OR cell
```

Prefer specific single terms and remove generic words such as:

```text
cell
blood
tissue
entity
```

Ancestor expansion lowers precision and should be pruned carefully.
