# Catalog read path — REST, record shape, and manual OLS

Reference material for the `catalog-query` skill. Direct REST via Python's standard library (`urllib`) is
the no-install default for reads; the CLI and SDK (see the main `SKILL.md`) add conveniences on top. Reach here when you need the
raw endpoints, the full record shape, or finer control over ontology expansion than
`scripts/search_expanded.py` gives.

## Direct REST (no install)

Paths are under `/api/`. The auth header is `X-catalog-api-token`; only paths under `/api/` accept it.
Use Python's standard library (`urllib`) — no third-party install, and the token stays in the header
(never on a command line, unlike `curl`):

```python
import json, os, urllib.parse, urllib.request
BASE = (os.environ.get("CATALOG_API_URL") or "https://datacatalog.prod-sci-data.prod.czi.team").rstrip("/")
H = {"X-catalog-api-token": os.environ["CATALOG_API_TOKEN"]}
q = urllib.parse.urlencode({"q": "liver", "limit": 10})
with urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/datasets/search/?{q}", headers=H)) as r:
    data = json.load(r)
```

## Read endpoints

List-style responses are `{total, limit, offset, results:[…]}`; `search` returns
`{total, limit, offset, results:[hit], facets}`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/datasets/search/` | **Free-text search** (see below). |
| GET | `/api/datasets/` | List / exact-match filter (no text search). |
| GET | `/api/datasets/{id}` | One full record. `id` is the UUID, not `canonical_id`. |
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
score`) and **omit `locations`** — fetch a full record via `list`/`get` to see a dataset's assets. Facet buckets are
**capped** at the top ~20–50 per field, so facets give the head, not distinct counts or the long tail —
page through for completeness.

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
- `locations: [{location_uri, asset_type, description, size_bytes, checksum, file_format, storage_platform}]`
- `governance: {license, access_scope, is_pii, is_phi, data_owner, embargoed_until, …}`
- `metadata: {experiment{sub_modality, assay, …}, sample{organism, tissue, disease, …},
  data_summary{cell_count, feature_count, channels, …}}`
- `incoming_lineage`, `outgoing_lineage`, `collections` — populated with `include_lineage=true` /
  `include_collections=true`.

`modality` ∈ `imaging | sequencing | mass spec | unknown`; `dataset_type` ∈ `raw | processed`.

## OLS expansion (the `ols` MCP is the primary source)

Term expansion happens **agent-side via the `ols` MCP**, then the terms go to `scripts/search_expanded.py
--terms …` for the multi-pass union (a subprocess can't reach the session's MCP connection). The script's
`--q` path is a REST fallback that only covers label + synonyms (+ subtypes); use the MCP tools directly
for anything richer — a specific hierarchy walk, embedding neighbours, etc.

The plugin ships the **OLS MCP server** (`ols`, EBI Ontology Lookup Service) at
`https://www.ebi.ac.uk/ols4/api/mcp`. Use its tools directly — no install, no token:

| OLS tool | Use it to |
|----------|-----------|
| `search` / `searchClasses` | Resolve a term → matching ontology classes (label, IRI, `obo_id`, synonyms). Start here. |
| `fetch` | Pull one class by the id `search` returned (full synonym list, definition). |
| `getChildren` / `getDescendants` | Expand a broad term into its subtypes (e.g. "brain" → its sub-regions). |
| `searchWithEmbeddingModel` / `getSimilarClasses` | Semantic / embedding neighbours when exact + synonym passes come up thin. |

Workflow: `search` the term with the `ols` MCP (scope to `uberon`/`cl`/`efo`/`mondo` when known) →
collect label + synonyms (optionally `getDescendants` for subtypes) → run one search per term and
**union by dataset `id`** → tell the user which expanded terms were searched. `scripts/search_expanded.py
--terms "t1,t2,…"` automates that union if the client is installed; with no install, do it in Python —
one `GET /api/datasets/search/?q=<term>` per term (stdlib `urllib`, as above), deduped by `id`.

If the `ols` MCP tools are unavailable, `search_expanded.py --q <term>` falls back to the OLS4 REST API
(no auth) internally:
`GET https://www.ebi.ac.uk/ols4/api/search?q=<term>&fieldList=label,obo_id,synonym,ontology_name&rows=5`
— reading `response.docs[].label` and `synonym[]`.
