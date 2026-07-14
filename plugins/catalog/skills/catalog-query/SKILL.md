---
name: catalog-query
description: Reads and queries the Scientific Dataset Catalog — free-text dataset search, list/filter, fetch by id, browse collections, trace lineage, filter data assets by description — via the catalog CLI, the catalog-client SDK, or direct REST, with OLS ontology expansion to broaden biological search terms. Use when asked to search/find datasets, look up a dataset by id or canonical_id, list datasets in a project, filter data assets by description, browse collections, or trace dataset lineage. The read companion to catalog-register (which handles writes).
---

# Query the Scientific Dataset Catalog

`catalog-client` is the Python SDK for the Scientific Dataset Catalog API. This skill covers the
**read path** — search, list, get, collections, lineage, asset filtering — through the `catalog` CLI
(quickest), the SDK (most flexible), or direct REST. For *writing* datasets (registration), use the
`catalog-register` skill instead.

**Better biological search:** before searching, expand the user's term with the **OLS ontology MCP**
(synonyms, subtypes) so a query for "liver" also catches "hepatic", "hepatocyte", etc. See
[Broaden search terms with OLS](#broaden-search-terms-with-ols-ontology-expansion).

## Configure

- **Base URL** is instance-specific; the `catalog-register` script convention reads it from
  `CATALOG_API_URL`. Issue an API token at `<base_url>/docs` → Token section (the `/docs` page may be
  SSO-gated — open it in a logged-in browser).
- **Token**: read from `CATALOG_API_TOKEN`; never hard-code it. The REST auth header is
  `X-catalog-api-token`; only paths under `/api/` accept it.

## Quickest: the `catalog` CLI

Installing the client (below) also installs a read-only `catalog` console script. It reads the same
`CATALOG_API_URL` / `CATALOG_API_TOKEN` env vars, prints an aligned table on a terminal and JSON when
piped (`-o json` to force), and exits non-zero on error (3 auth, 4 not-found, 5 server). Prefer it for
one-off lookups; drop to the SDK when you need to script logic over the results.

```bash
catalog search --q liver --modality sequencing --facets project --limit 10
catalog facets --fields organism,tissue,assay        # discover the real filter vocabulary
catalog get <dataset-uuid> --lineage --collections   # or: get <canonical_id> --version V --project P
catalog list --project CellXGene --modality imaging --limit 100
catalog lineage <dataset-uuid> --direction up --depth 3
catalog collections entries <collection-uuid>
```

Subcommands: `search`, `facets`, `get`, `list`, `lineage`, `collections`. Run `catalog <cmd> -h` for
flags. The CLI has no asset-description filter — for that use the bundled
[`filter_assets.py`](#filter-data-assets-by-description) script.

## Preferred for scripting: the catalog-client SDK

Typed pydantic models, correct param handling, all endpoints. Install a pinned release (never `main`):

```bash
pip install 'git+https://github.com/chanzuckerberg/dataset-catalog.git@catalog-client-v0.3.0#subdirectory=dataset-catalog-client'
```

```python
import os
from catalog_client import CatalogClient

with CatalogClient(base_url=os.environ["CATALOG_API_URL"],
                   api_token=os.environ["CATALOG_API_TOKEN"]) as cat:
    hits  = cat.datasets.search(q="liver", modality="sequencing", facets=["project"], limit=10)
    page  = cat.datasets.list(project="…", is_latest=True, limit=100)
    one   = cat.datasets.get(dataset_id)          # or a DatasetRef(canonical_id, version, project)
    cols  = cat.collections.list(limit=100)
    edges = cat.lineages.list(source_dataset_id=dataset_id)
```

Constructor is `CatalogClient(base_url, api_token, timeout=30.0)`; `AsyncCatalogClient` mirrors it under
`async with`. Sub-clients: `.datasets`, `.collections`, `.lineages`. Requires Python ≥3.12.

## Fallback: direct REST (no install)

```python
import os, requests
BASE = os.environ["CATALOG_API_URL"].rstrip("/")
H = {"X-catalog-api-token": os.environ["CATALOG_API_TOKEN"]}
r = requests.get(f"{BASE}/api/datasets/search/", headers=H, params={"q": "liver", "limit": 10})
r.raise_for_status(); r.json()
```

## Read endpoints

Paths are under `/api/`. List-style responses are `{total, limit, offset, results:[…]}`; `search`
returns `{total, limit, offset, results:[hit], facets}`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/datasets/search/` | **Free-text search** (see below). |
| GET | `/api/datasets/` | List / exact-match filter (no text search). |
| GET | `/api/datasets/{id}` | One full record. `id` is the UUID, not `canonical_id`. |
| GET | `/api/datasets/{id}/history` | Audit log (`actor`, `event_type`, `start_time`, `end_time`, `skip`, `limit`). |
| GET | `/api/collections/` | List collections (filters `canonical_id`, `version`). |
| GET | `/api/collections/{id}` | One collection. |
| GET | `/api/collections/{id}/entries` · `/parents` | Child / parent membership (`entry_type`). |
| GET | `/api/lineage/` | Lineage edges (`source_dataset_id`, `destination_dataset_id`, `lineage_type`). |
| GET | `/api/lineage/{edge_id}` | One edge. |

`id` ≠ `canonical_id`: `/api/datasets/{id}` wants the UUID; filter by `canonical_id=` to resolve one.

## Search vs. list — pick the right one

**Free-text → `/api/datasets/search/`.** Query param `q`, plus filters `modality`, `project`,
`is_latest`, `access_scope`, `organism`, `tissue`, `sub_modality`, `assay`, `disease`,
`development_stage`; `facets=[…]` (repeatable) returns bucket counts; `sort` ∈ `relevance` (default),
`alphabetical`, `last_modified`, `newest`, `oldest`. **Default `limit` is 10.** Results are lightweight
hits (`id, canonical_id, version, name, modality, dataset_type, project, is_latest, access_scope,
score`). Facet buckets are **capped** at the top ~20–50 per field, so facets give the head, not distinct
counts or the long tail — page through for completeness.

**Exact-match filtering → `/api/datasets/`.** Keyword filters `canonical_id`, `version`, `modality`,
`project`, `access_scope`, `is_latest`, plus toggles `exclude_tombstoned` (default true),
`include_lineage`, `include_collections` (default false — set true to inline them), `offset`, `limit`.

### Gotchas
- **`limit` caps at 100** on list routes (`limit>100` → HTTP 422); page with `offset`.
- **The list route silently ignores unknown query params** — no 422, and `total` comes back unchanged.
  There is **no `?search=`** on the list route (text search lives on `/api/datasets/search/`), and
  fields like `dataset_type` are search facets, not list filters. **Never trust a list filter until you
  have watched `total` drop.**
- **Aggregate fields can be scoped above the record.** Some collections stamp a batch- or atlas-level
  value (e.g. `data_summary.cell_count`) onto every constituent dataset, so *summing* such a field
  across datasets multiplies it. Report per-dataset values, or dedupe to canonical datasets first.
- `/docs` and `/openapi.json` may be SSO-gated — the API token alone won't fetch them.

## Broaden search terms with OLS (ontology expansion)

Catalog search matches the **text that was indexed** — a dataset tagged "hepatic" won't surface for
`q=liver`. To raise recall, expand the user's biological term into its canonical label, synonyms, and
subtypes *before* searching, then run several passes and union the results.

The plugin ships an **OLS MCP server** (`ols`, EBI Ontology Lookup Service). Use its tools directly —
no install, no token:

| OLS tool | Use it to |
|----------|-----------|
| `search` / `searchClasses` | Resolve a term → matching ontology classes (label, IRI, `obo_id`, synonyms). Start here. |
| `fetch` | Pull one class by the id `search` returned (full synonym list, definition). |
| `getChildren` / `getDescendants` | Expand a broad term into its subtypes (e.g. "brain" → its sub-regions) for extra query passes. |
| `searchWithEmbeddingModel` / `getSimilarClasses` | Semantic / embedding neighbours when exact + synonym passes come up thin. |

Workflow:
1. `search` the user's term in OLS (scope to a relevant ontology such as `uberon`/`cl`/`efo`/`mondo`
   when you know it) to get the canonical label + synonyms; optionally `getDescendants` for subtypes.
2. Run `catalog search --q <term>` once per distinct label/synonym, then **union by dataset `id`**.
3. Tell the user which expanded terms you searched, so a broadened match is never mistaken for an exact
   name hit.

If the `ols` MCP tools are not available in the session, fall back to the OLS4 REST API (no auth):
`GET https://www.ebi.ac.uk/ols4/api/search?q=<term>&fieldList=label,obo_id,synonym,ontology_name&rows=5`
— read `response.docs[].label` and `synonym[]`.

## Pagination

`limit ≤ 100`; page with `offset` (SDK: loop on `len(resp.results)`):

```python
def iter_datasets(cat, **filters):
    offset = 0
    while True:
        page = cat.datasets.list(offset=offset, limit=100, **filters).results
        if not page:
            return
        yield from page
        offset += len(page)
```

## Dataset record shape

`id, canonical_id, version, project, name, description, modality, doi, dataset_type, is_latest,
tombstoned, created_at, last_modified_at`, plus:
- `locations: [{location_uri, asset_type, description, size_bytes, checksum, file_format, storage_platform}]`
- `governance: {license, access_scope, is_pii, is_phi, data_owner, embargoed_until, …}`
- `metadata: {experiment{sub_modality, assay, …}, sample{organism, tissue, disease, …},
  data_summary{cell_count, feature_count, channels, …}}`
- `incoming_lineage`, `outgoing_lineage`, `collections` — populated with `include_lineage=true` /
  `include_collections=true`.

`modality` ∈ `imaging | sequencing | mass spec | unknown`; `dataset_type` ∈ `raw | processed`.

## Filter data assets by description

Data assets (`locations`) live **inside** the dataset record — there is no asset search endpoint and no
`description` filter on any list/search route. To find assets whose description mentions something, you
must fetch dataset records and filter their `locations` client-side. The bundled
[`scripts/filter_assets.py`](scripts/filter_assets.py) does exactly this:

```bash
# assets whose description mentions "segmentation mask", within one project
python scripts/filter_assets.py --description "segmentation mask" --project CellXGene

# combine with format / type filters; JSON out
python scripts/filter_assets.py --description mask --file-format tiff --modality imaging -o json
```

Matching is case-insensitive substring on the asset `description` (and optionally `--file-format`
substring / `--asset-type` exact). At least one asset filter is required. Because it walks whole dataset
records, **narrow the scan** with dataset filters (`--project`, `--modality`, `--canonical-id`,
`--access-scope`, `--all-versions`); `--scan-limit` (default 1000) caps datasets scanned and **warns on
stderr** when more matched, and `--limit` (default 100) caps assets returned. Requires the same
`CATALOG_API_URL` / `CATALOG_API_TOKEN` env vars and the installed `catalog_client`.

To do the same in your own code: iterate `cat.datasets.list(...)` (each `DatasetWithRelationsResponse`
carries `locations`) and keep assets where `substr.lower() in (asset.description or "").lower()`. Note
`search` hits are lightweight and **omit** `locations`, so asset filtering must build on `list`/`get`.
