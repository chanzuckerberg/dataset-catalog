---
name: catalog-query
description: Reads and queries the Scientific Dataset Catalog — free-text dataset search, list/filter, fetch by id, browse collections, trace lineage — via the catalog-client SDK or direct REST. Use when asked to search/find datasets, look up a dataset by id or canonical_id, list datasets in a project, browse collections, or trace dataset lineage. The read companion to catalog-register (which handles writes).
---

# Query the Scientific Dataset Catalog

`catalog-client` is the Python SDK for the Scientific Dataset Catalog API. This skill covers the
**read path** — search, list, get, collections, lineage — through the SDK (preferred) or direct REST.
For *writing* datasets (registration), use the `catalog-register` skill instead.

## Configure

- **Base URL** is instance-specific; the `catalog-register` script convention reads it from
  `CATALOG_API_URL`. Issue an API token at `<base_url>/docs` → Token section (the `/docs` page may be
  SSO-gated — open it in a logged-in browser).
- **Token**: read from `CATALOG_API_TOKEN`; never hard-code it. The REST auth header is
  `X-catalog-api-token`; only paths under `/api/` accept it.

## Preferred: the catalog-client SDK

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
- `locations: [{location_uri, asset_type, size_bytes, checksum, file_format, storage_platform}]`
- `governance: {license, access_scope, is_pii, is_phi, data_owner, embargoed_until, …}`
- `metadata: {experiment{sub_modality, assay, …}, sample{organism, tissue, disease, …},
  data_summary{cell_count, feature_count, channels, …}}`
- `incoming_lineage`, `outgoing_lineage`, `collections` — populated with `include_lineage=true` /
  `include_collections=true`.

`modality` ∈ `imaging | sequencing | mass spec | unknown`; `dataset_type` ∈ `raw | processed`.
