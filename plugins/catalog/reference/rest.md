# REST API Calls: Catalog Reads and OLS expansion

Use this reference when you need REST Catalog API access, or manual ontology expansion.

For ordinary reads, use Python’s standard-library REST path. It requires no installation. The `catalog` CLI and `catalog_client` SDK provide optional conveniences such as pagination, fan-out, result union, and typed post-processing. The bundled scripts' REST fallback self-heals on endpoint moves: on a 404/405 it re-resolves the current dataset routes from the live spec and retries once.

## Endpoints are discovered, not memorized

**The API is still in flux.** Every literal path, parameter list, and response
shape in this document is a snapshot captured at authoring time — treat them
as defaults that can drift, not as contracts. The live OpenAPI spec is the
only source of truth, and the bundled discovery script is how you read it
without pulling thousands of spec lines into context:

```bash
# every operation the API currently exposes (method, path, summary):
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/api_map.py"

# params (with enums/defaults) + response fields for matching operations:
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/api_map.py" datasets/search
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/api_map.py" lineage --json
```

The script probes the known spec locations (`/api/meta/openapi.json` and
fallbacks) with the token header, so a relocated spec degrades to a slower
first call rather than a broken skill. It is read-only and auto-approved by
the plugin hook.

When to discover:

* **Once per session, before the first scripted call** — confirm the paths and
  parameters you're about to rely on.
* **On any `404`/`405` for a documented path, or a `422` for a documented
  parameter** — the surface moved; rediscover and adapt. Never conclude "the
  data is gone" or "the filter doesn't exist" from a stale path.
* **Before parsing a response shape you haven't seen this session.**

Allowed values for parameters like `facets`, `fields`, and `sort` often live
in the parameter `description` — `api_map.py` prints it. If the script is
unavailable, fetch the spec directly (`GET /api/meta/openapi.json` with the
token header) and extract the same information; the interactive `/docs` page
may sit behind SSO, so don't use it.

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

## Read endpoints (as of authoring — discover the current set with `api_map.py`)

| Path                                   | Purpose                                    |
| -------------------------------------- | ------------------------------------------ |
| `GET /api/datasets/search/`            | Free-text dataset search (ranked, faceted) |
| `GET /api/datasets/`                   | List datasets or apply exact-match filters |
| `GET /api/datasets/{id}`               | Fetch one full dataset record              |
| `GET /api/datasets/{id}/history`       | Version history for a dataset              |
| `GET /api/collections/`                | List collections                           |
| `GET /api/collections/{id}`            | Fetch one collection                       |
| `GET /api/collections/{id}/entries`    | Fetch child membership                     |
| `GET /api/collections/{id}/parents`    | Fetch parent membership                    |
| `GET /api/lineage/`                    | List lineage edges                         |
| `GET /api/lineage/{edge_id}`           | Fetch one lineage edge                     |
| `GET /api/meta/openapi.json`           | Live OpenAPI spec (source of truth)        |

`/api/datasets/{id}` requires the dataset UUID, not its `canonical_id`. Resolve a canonical ID through the list route:

```
GET /api/datasets/?canonical_id=<value>
```

## Pagination — differs by endpoint

* `/api/datasets/search/` paginates with an **opaque cursor**: each page
  returns `next_cursor`; pass it back as `cursor` to fetch the next page
  (`null` means done). It does **not** page with `offset`.
* `/api/datasets/`, `/api/collections/*`, and `/api/lineage/` paginate with
  `offset`/`limit`. List-style responses have the shape
  `{total, limit, offset, results: […]}`.
* Search `limit` ranges 1–1000 (1–100 when `hydrate=true`); `limit=0` returns
  `422`. The default is 10.
* The list routes cap `limit` at 100; `limit > 100` returns HTTP 422.

## Search or list?

### Free-text search

Use:

```
GET /api/datasets/search/
```

Query parameters (all optional; confirm the current set against the spec):

* `q` — full-text search across indexed fields; name and description are
  weighted highest.
* Exact-match filters: `modality`, `sub_modality`, `assay`, `organism`,
  `tissue`, `disease`, `development_stage`, `project`, `cohort`,
  `access_scope`, `file_format`, `storage_platform`, `is_latest`.
* `facets` — field(s) to return value counts for; repeat for multiple.
* `fields` — extra fields to include per hit beyond the core set; repeat for
  multiple (e.g. `description`, `data_owner`, `data_steward`, `locations`,
  `collections`, `doi` — full list in the spec).
* `sort` — `relevance` (default), `alphabetical`, `last_modified`, `newest`,
  `oldest`.
* `hydrate` — `true` re-reads each hit from the DB and returns the full
  dataset record. Use it when several hits need full records: one hydrated
  search replaces a detail call per hit.
* `cursor` — pass the previous page's `next_cursor` to page forward.
* `limit` — see *Pagination* above.

Search hits are lightweight by default, containing fields such as:

```text
id, canonical_id, version, name, modality, dataset_type,
project, is_latest, access_scope, score
```

Default hits do not contain `locations`. Add `fields=locations`, set
`hydrate=true`, or fetch the full record to inspect assets.

`q` is weak on accession-named data: some projects name datasets by an
external accession rather than a descriptive title, so a natural-language `q`
can legitimately return 0 for data that exists. Drive discovery of such
projects with exact-match filters plus facets, not `q`.

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

Allowed facet fields (confirm against the spec's `facets` parameter
description, which is authoritative):

```text
access_scope, assay, cohort, dataset_type, development_stage, disease,
file_format, license, modality, organism, project, storage_platform,
sub_modality, tissue
```

The client does not validate facet names; an unsupported field returns `422`
from search. Facet semantics:

* Buckets include **only non-null values**. Datasets missing the field
  contribute to no bucket, so bucket counts can sum to less than `total`.
* Facet counts are independent of `limit` — use `limit=1` to fetch a facet
  breakdown without pulling records.
* Whether the bucket list is capped varies by deployment; before treating a
  bucket list as the complete distinct-value set, confirm against the spec or
  sanity-check against a known enumeration.

## Data cautions

* Aggregate fields like `data_summary.cell_count` may be collection-level values repeated on every constituent dataset. Do not sum them blindly. Report per-dataset values or deduplicate canonical datasets first.
* Tombstoned records are excluded by default; only surface them when the user is explicitly auditing deletions.

SDK pagination example (list routes):

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

Allowed values include:

```text
modality: imaging | sequencing | mass spec | unknown
dataset_type: raw | processed
```

### Where fields live

Domain metadata is nested, not top-level; inspect a sample record (or
`components.schemas` in the spec) before parsing. Common groupings:

| Group | Path on the dataset record |
| --- | --- |
| Experiment (assay, protocols, source records, …) | `metadata.experiment.*` |
| Sample (organism, tissue, disease, …) | `metadata.sample.*` (ontology label + id) |
| Pipeline / compute context | `metadata.additional_metadata.*` |
| QC / metrics | `data_quality.*` (e.g. `data_quality.metrics`) |
| File paths + formats | `locations[].location_uri`, `locations[].file_format` |
| Governance | `governance.*` (`access_scope`, `data_steward`, `data_owner`, …) |

A given attribute may only appear on one record type in a lineage chain (e.g.
present on a raw input but not on its derived output) — join it from the
record that actually carries it.

## Lineage and collections

**Search does not expand relationships.** Take dataset ids from search and
pivot to these routes.

> **Gotcha:** the detail endpoint `GET /api/datasets/{id}` returns
> `incoming_lineage`, `outgoing_lineage`, and `collections` as **`null`** — it
> does *not* embed relationships. To get lineage or collections for a known
> dataset, use the list route with the include flags —
> `GET /api/datasets/?canonical_id=<cid>&include_lineage=true&include_collections=true`
> — or the dedicated `/api/lineage/` endpoint. **Never conclude "no lineage"
> from a detail-endpoint response.** An empty edge list from `/api/lineage/`
> (or `total=0`) is the real "no lineage recorded" answer.

* Lineage edges are directed records (`source_dataset_id`,
  `destination_dataset_id`, optional asset-level ids, `lineage_type`,
  `metadata`). Query `/api/lineage/?source_dataset_id=<id>` for downstream,
  `?destination_dataset_id=<id>` for upstream.
* **Edges carry only ids, not the linked records.** To get a neighbor's name,
  format, or file path, fetch that dataset by id.
* Collection entries (`GET /api/collections/{id}/entries`) each have an
  `entry_type` (`dataset` or `child_collection`) with the full member object
  embedded under `entry`, so listing entries yields complete records in one
  call. Collections can nest; walk upward with `/parents`.

## Failure modes

| Symptom | Handling |
| --- | --- |
| HTML redirect to an SSO login page | The call went out without (or with a bad) `X-catalog-api-token`, or hit a non-`/api` path behind the auth proxy. Set the header; use `/api/...` paths. |
| `401` `{"detail":"Missing required header: X-catalog-api-token"}` | Header name/value wrong. It is `X-catalog-api-token`, not `Authorization: Bearer`. |
| `401` (token rejected) | Token missing/expired/wrong environment. Ask the user to refresh `CATALOG_API_TOKEN`; do not retry in a loop. |
| `422` | Invalid parameter or value (e.g. a `facets`/`sort` value outside the allowed list, `limit=0`, list `limit>100`). Fix the parameter; check the spec. |
| `503` | Search backend unavailable. Retry once, then report — never substitute guessed data. |
| `404` on a dataset id | Wrong or tombstoned id; re-run search or the list route to get a current id. |
| `404`/`405` on a documented *path*, or `422` on a documented *parameter* | The API surface moved since this doc was written. Run `scripts/api_map.py` to discover the current path/params and adapt — do not report the data or feature as missing. |

Always surface the HTTP status and response body on failure — a silent "not
found" that was actually an auth or validation error wastes the user's time.

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
