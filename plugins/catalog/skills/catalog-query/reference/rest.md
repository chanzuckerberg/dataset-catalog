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

**There is no facets endpoint.** Do **not** call `/api/datasets/facets/` (or `/api/facets/`) — it does not
exist. Facet counts are returned by `search`; see [Facets](#facets-no-dedicated-endpoint) below.

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

### Facets (no dedicated endpoint)

Facet counts are a **property of the search response**, not a separate route — there is no
`/api/datasets/facets/`. To count a field's values (i.e. discover its controlled vocabulary), call
`/api/datasets/search/` with one or more `facets=<field>` params and read the `facets` object off the
response. `facets` is a **repeated** query param (`facets=organism&facets=tissue`), *not* a comma-joined
string, so build the query with `doseq=True`:

```python
# BASE / H as in the Direct REST snippet above
import json, urllib.parse, urllib.request
qs = urllib.parse.urlencode({"facets": ["organism", "tissue", "assay"], "limit": 1}, doseq=True)
req = urllib.request.Request(f"{BASE}/api/datasets/search/?{qs}", headers=H)
with urllib.request.urlopen(req) as r:
    facets = json.load(r)["facets"]
# facets == {"organism": [{"value": "Homo sapiens", "count": 42}, ...], "tissue": [...], ...}
```

`GET /api/datasets/search/?facets=organism&facets=tissue&facets=assay&limit=1` is the raw form; scope the
counts to a subset by adding the usual search filters (`q`, `modality`, `project`, …). The `catalog facets
--fields organism,tissue` CLI command is exactly this call. Buckets are **capped** at the top ~20–50 per
field (see the cap note above), so facets give the head, not the full distinct set.

**Fields you can facet on.** The client does **not** validate facet field names (it forwards whatever you
pass), and this repo ships no schema enumerating them — the server is the authority. The safe candidates
are the search route's categorical filter dimensions:

| Field | Notes |
|-------|-------|
| `modality` | `imaging \| sequencing \| mass spec \| unknown` — confirmed facetable |
| `dataset_type` | `raw \| processed` — a search facet, **not** a list filter |
| `organism` | confirmed facetable |
| `tissue` | |
| `assay` | |
| `disease` | |
| `sub_modality` | |
| `development_stage` | |
| `project` | |
| `access_scope` | |

`modality` and `organism` are exercised by the client's tests; the rest are the remaining search filters,
so they are expected to facet but are **not verified here**. An unsupported field name doesn't error — it
simply won't appear in the response's `facets` object. So confirm any field empirically: request it and
check whether a bucket list comes back (or read the SSO-gated `/openapi.json` for the definitive set).

> Note: the `api_get` helper in the skill's Quick start already urlencodes with `doseq=True`, so pass
> `facets` as a **list** — `api_get(..., facets=["tissue", "modality"])` — and it repeats the key for you.
> Never comma-join (`facets="tissue,modality"`) — that is the usual cause of a 422 on this route.

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
`--q` path is a REST fallback that covers label + synonyms and, on request, immediate children
(`--children`), the full subtype subtree (`--subtypes`), and broader ancestors (`--ancestors`); use the
MCP tools directly for anything richer — a specific hierarchy walk, embedding neighbours, etc.

The plugin ships the **OLS MCP server** (`ols`, EBI Ontology Lookup Service) at
`https://www.ebi.ac.uk/ols4/api/mcp`. Use its tools directly — no install, no token:

| OLS tool | Use it to |
|----------|-----------|
| `search` / `searchClasses` | Resolve a term → matching ontology classes (label, IRI, `obo_id`, synonyms). Start here. |
| `fetch` | Pull one class by the id `search` returned (full synonym list, definition). |
| `getChildren` | **Immediate children** — direct subtypes one level down (e.g. `blood` → arterial/venous/capillary/placental blood). Tightest hierarchy expansion. |
| `getDescendants` | **Full subtype subtree** — every subtype below the term (e.g. "brain" → all sub-regions). Broadest subtype recall. |
| `getAncestors` | **Broader parent terms** (e.g. `blood` → haemolymphatic fluid → bodily fluid). Only expand when the starting term is **already super granular** (a deep leaf class whose parents are still meaningful); for an already-broad term the first hop is generic, so skip it. Raises recall, lowers precision — prune generic terms. |
| `searchWithEmbeddingModel` / `getSimilarClasses` | Semantic / embedding neighbours when exact + synonym passes come up thin. |

Workflow: `search` the term with the `ols` MCP (scope to `uberon`/`cl`/`efo`/`mondo` when known) →
collect label + synonyms, and as needed `getChildren` (immediate subtypes), `getDescendants` (full
subtree), or `getAncestors` (broader terms) → run one search per term and **union by dataset `id`** →
tell the user which expanded terms were searched. `scripts/search_expanded.py --terms "t1,t2,…"`
automates that union if the client is installed; with no install, do it in Python — one
`GET /api/datasets/search/?q=<term>` per term (stdlib `urllib`, as above), deduped by `id`.

**Precision caveat:** free-text `q=` is OR-tokenized, so a multi-word term matches on any single token
and recall is dominated by its most generic word (`q="red blood cell"` ≈ `red OR blood OR cell`). Search
single, specific tokens; drop generic ones (`cell`, `blood`, `tissue`, `entity`). This is why ancestors
need pruning — they resolve to exactly those broad terms.

If the `ols` MCP tools are unavailable, `search_expanded.py --q <term>` falls back to the OLS4 REST API
(no auth) internally:
`GET https://www.ebi.ac.uk/ols4/api/search?q=<term>&fieldList=label,obo_id,synonym,ontology_name&rows=5`
— reading `response.docs[].label` and `synonym[]`. With `--children`/`--subtypes`/`--ancestors` it then
walks `GET /ontologies/{ontology}/terms/{double-url-encoded-iri}/{children|descendants|ancestors}`,
reading `_embedded.terms[].label` (for ancestors, upper-ontology classes are dropped by ID namespace —
`BFO`/`CARO`/`COB`/… — since OLS reports them under the importing ontology, not their own).
