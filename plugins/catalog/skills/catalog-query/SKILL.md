---
name: catalog-query
description: Read-only querying of the Scientific Dataset Catalog — free-text dataset search (optionally broadened with ontology terms via the ols MCP), look-ups by id or canonical_id, project dataset listings, collection browsing, and lineage tracing. Use when asked to search or find datasets, fetch a dataset by id/canonical_id, list a project's datasets, browse collections, or trace lineage.
---

# Query the Scientific Dataset Catalog

This skill covers the **read path** of the Scientific Dataset Catalog — search, list, get of datasets,
collections, lineage.

The common reads — **search, list, get by id** for datasets — are plain HTTP GETs and need **no
install**: call the REST API from Python's standard library (`urllib`, see [Quick start](#quick-start)),
which reads the token from the environment so it never lands on a command line. Even **ontology-broadened
search** works with no install — expand the term with the `ols` MCP, then run one search per term and
union the hits by dataset `id` yourself. Install the `catalog` CLI or the `catalog_client` SDK for the
conveniences: the bundled `search_expanded.py` automates that fan-out and union, plus page iteration,
typed post-processing, and whatever extra filters the latest client adds.

## Preflight — do this before any query

Every command below assumes the following are already true. Check them first; don't discover a missing
one three steps into a query.

1. **Config is set.** `CATALOG_API_TOKEN` must be in the environment; `CATALOG_API_URL` is optional.
   - **URL:** if `CATALOG_API_URL` is unset, it defaults to the production instance
     `https://datacatalog.prod-sci-data.prod.czi.team/` — set it only to target another instance.
   - **Token:** if `CATALOG_API_TOKEN` is unset, it cannot be minted headlessly — it is issued through an
     SSO-gated page that needs a human. Open the token page in the user's (already logged-in) default
     browser so they can generate one:
     ```bash
     URL="${CATALOG_API_URL:-https://datacatalog.prod-sci-data.prod.czi.team}"
     open "${URL%/}/tokens"          # macOS; Linux: xdg-open …  Windows: start "" …
     ```
     Then ask the user to copy the token into their **Claude Code env settings** (the `env` block in
     `settings.json` — the `update-config` skill can do this) rather than pasting it into the chat, and
     never inline it into a command: that keeps the secret out of the transcript and logs. Once it's set,
     re-run this check and proceed.
2. **Install only what the task needs.** The REST path (get/list/search) runs on Python's standard
   library — nothing to install. The `catalog` CLI and the `catalog_client` SDK add conveniences but need
   the package installed (confirm with `catalog --version` or `python -c "import catalog_client"`, and if
   missing install a tagged release, [Install](#install)); `search_expanded.py` *uses* the SDK when it's
   installed and otherwise falls back to the same stdlib REST calls. Don't install just to run a read.

## Quick start

The three common reads are plain `GET`s under `/api/`, authed with the `X-catalog-api-token` header, and
run on the **Python standard library — no install**. The token is read from the environment and sent as a
header, so it never appears on a command line (the reason we don't use `curl`). Set `CATALOG_API_URL` +
`CATALOG_API_TOKEN` (see [Configure](#configure)), then:

```python
import json, os, urllib.parse, urllib.request

BASE = (os.environ.get("CATALOG_API_URL") or "https://datacatalog.prod-sci-data.prod.czi.team").rstrip("/")
HEADERS = {"X-catalog-api-token": os.environ["CATALOG_API_TOKEN"]}  # token stays in env, never on argv

def api_get(path, **params):
    # doseq=True is REQUIRED: a list value must repeat the key (facets=tissue&facets=modality),
    # NOT comma-join. Passing facets="tissue,modality" is the #1 cause of HTTP 422 here.
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
    url = f"{BASE}{path}" + (f"?{query}" if query else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS)) as r:
        return json.load(r)

# 1. search datasets — free text + optional facet filters (e.g. modality, project, tissue)
api_get("/api/datasets/search/", q="liver", modality="sequencing", limit=10)

# 2. list a project's datasets — exact-match filters; paginate with offset (limit caps at 100)
api_get("/api/datasets/", project="CellXGene", limit=100)

# 3. fetch one full record by UUID (add include_lineage="true" / include_collections="true" to embed)
api_get("/api/datasets/<dataset-uuid>")

# 4. discover a facet's controlled vocabulary — facets is a LIST (doseq=True repeats the key)
api_get("/api/datasets/search/", facets=["tissue", "modality"], limit=1)["facets"]
```

`api_get` returns parsed JSON (a dict). Endpoints, every filter, pagination, and the full record shape
are in [reference/rest.md](reference/rest.md). Ontology-broadened search is also no-install — see
*Search: broaden biological terms* below. Reach for the CLI/SDK/script when you want the automated union,
page iteration, or typed post-processing.

## Configure

- **Base URL** is instance-specific; read it from `CATALOG_API_URL`. Default (production):
  `https://datacatalog.prod-sci-data.prod.czi.team/`.
- **Token**: read from `CATALOG_API_TOKEN`; never hard-code it. Issue one at `<base_url>/tokens` — open
  it in a logged-in browser (the page is SSO-gated) — then store it in your Claude Code env settings.

## Install

Needed only for the CLI/SDK/script — the REST path above needs none of this. The `catalog` CLI and the
`catalog_client` SDK ship in one package; the bundled `search_expanded.py` needs only that package plus
the standard library. Install a **tagged release, never `main`**. Full steps (tag resolution, venv,
monorepo `uv`) are in **[reference/install.md](reference/install.md)**.

## Which surface to use

- **Direct REST (Python `urllib`)** — the default for simple get/list/search; no install, token stays in
  the env (never on a command line). See [Quick start](#quick-start) and [reference/rest.md](reference/rest.md).
- **`catalog` CLI** — installed convenience for one-off lookups: aligned table on a terminal, JSON when
  piped (`-o json` to force); exits non-zero on error (3 auth, 4 not-found, 5 server).
- **`catalog_client` SDK** — when you need to iterate, join, or post-process results in code. Typed
  pydantic models, all endpoints.
- **Bundled script** — `search_expanded.py` automates ontology-broadened search (the multi-term fan-out
  + union by `id`) in one call. You can do the same by hand in Python; the script just wraps it and
  adds term-match reporting, fan-out caps, and the client's filters. It uses the SDK when installed and
  otherwise the same stdlib REST calls, so it runs with no install too.

## Delegate to the `catalog-reader` agent by default

**Default to delegating the query to the plugin's `catalog-reader` subagent.** It runs the queries in its
own context and returns only the distilled result (the datasets that matched, their ids and the requested
fields), so paginated JSON, facet dumps, and full-record output never land in the main conversation. Hand
it the task in words ("find raw sequencing datasets in blood, broken down by project") and let it do the
facet discovery, filtering, and pagination.

Delegate whenever a query **could** touch more than one record or one page — searches, facet discovery,
project/collection listings, lineage traces, any client-side filtering (e.g. `dataset_type`, which is a
facet, not a server filter, so it forces a paginated sweep). You usually can't tell up front that a query
is small: a two-facet search that looks trivial can turn into paging thousands of records. When in doubt,
delegate — an over-delegated `get` costs a little overhead; an inline sweep floods this context with JSON
and invites the retry-in-the-open failures this skill exists to prevent.

**Run inline only** for a genuinely bounded single call: one `get` by known UUID/`canonical_id`, or one
`search`/facet call you will read once and not paginate. And **always run ontology expansion inline**
(next section) — the `ols` MCP is a session connection the subagent can't reach; expand agent-side, then
hand the expanded terms to `catalog-reader`.

(If you delegate a *bare* biological term without expanding it first, the agent falls back to the script's
OLS4 REST expansion — `search_expanded.py --q --ontology …` — which covers label + synonyms only, so
recall is thinner than an `ols` MCP expansion done agent-side.)

## Search: broaden biological terms (ols MCP + `search_expanded.py`)

### First: is this a facet filter or a free-text term?

Before expanding anything, decide *where* the term belongs. The catalog has controlled facet dimensions
— `organism`, `tissue`, `assay`, `disease`, `sub_modality`, `development_stage`, `modality` — and a
free-text `q=` index over name/metadata. They are not interchangeable:

- **If the term names a facet dimension** (e.g. "blood" is a tissue, "10x" an assay), prefer the **facet
  filter** — `catalog search --tissue blood`, or in REST `&tissue=blood` on the search route — which is
  an exact match against a curated value and far more precise than free text. Two rules, in order:
  1. **Confirm the exact spelling first — facet values are a controlled vocabulary.** In REST that means a
     `search` call with the facet field(s) read off the response's `facets` object (there is **no**
     `/api/datasets/facets/` endpoint; see [reference/rest.md](reference/rest.md)). Use this exact call and
     do **not** improvise the encoding — `facets` is a **repeated** param, so pass it as a **list** through
     the `doseq=True` helper; comma-joining it (`facets="tissue,modality"`) returns HTTP 422:
     ```python
     # api_get is the doseq=True helper from Quick start
     api_get("/api/datasets/search/", facets=["tissue", "modality"], limit=1)["facets"]
     ```
     Confirm the value is real before you filter on it: the list route **silently ignores** an unknown
     filter, so a wrong value reads as "matched everything". OLS synonyms/subtypes are *not* guaranteed to
     be valid facet values.
  2. **Filter on the facet alone — do not also pass the same word as free-text `q=`.** Stacking
     `q="blood"` on top of `tissue="blood"` double-filters: a record only survives if the literal word
     "blood" also appears in indexed text, which silently craters recall (in one run, 33 hits instead of
     the real 1970). Use `q=` only for a *different* concept than the facet, or not at all.
- **If the concept is not a facet, or the facet vocabulary doesn't cover the synonyms/subtypes you need
  for recall**, fall back to free-text `q=` expansion (below). You can also combine the two — a facet
  filter to scope, `--terms` for recall within it — but only union free-text passes when the facet alone
  under-recalls.

The ontology-expansion machinery below feeds the **free-text `q=` path** (`--terms`). It does *not* widen
a facet filter, so don't reach for it when a single precise facet value answers the question.

### Raising recall on the free-text path

Catalog search matches only the **text that was indexed** — a dataset tagged "hepatic" won't surface for
`q=liver`. Raising recall is a two-part job, split by *who can do what*:

1. **Expand the term via the plugin's `ols` MCP server** (EBI Ontology Lookup Service). Call its tools
   directly, agent-side (the `ols` MCP is a session connection a subprocess can't reach), and gather
   related terms from several relations:
   - `search`/`searchClasses` — resolve the term to a class (canonical **label + synonyms**). Always do this.
   - `getChildren` — the **immediate children** (one level down): the direct subtypes, e.g. `blood` →
     `arterial/venous/capillary/placental blood`. Prefer this when you want tight, obviously-related
     subtypes rather than the whole subtree.
   - `getDescendants` — the **full subtype subtree**, when you want maximum subtype recall.
   - `getAncestors` — **broader parent terms**, e.g. `blood` → `haemolymphatic fluid` → `bodily fluid`.
     **Only expand ancestors when the starting term is already super granular** — a deep, specific leaf
     class (e.g. `CD8-positive, alpha-beta memory T cell`), whose immediate parents are still meaningful.
     For a term that is already broad (like `blood`), the very first hop is generic, so ancestors add
     only noise — skip them. Even for a granular term, prune hard: the walk climbs toward upper-ontology
     terms (`material entity`, `anatomical entity`) that match everything (see the precision note below).
2. **Union the passes by dataset `id`** — run one search per expanded term and merge, deduped on `id`, so
   a dataset matching several synonyms is reported once. Same result either way:
   - **No install** — reuse `api_get` from Quick start; one call per term, union by `id` (`urllib`
     handles URL-encoding, so multi-word terms are fine):
     ```python
     terms = ["liver", "hepatic", "hepatocyte"]        # expanded by the ols MCP
     merged = {}
     for t in terms:
         for hit in api_get("/api/datasets/search/", q=t, modality="sequencing", limit=25)["results"]:
             merged.setdefault(hit["id"], hit)         # dedupe by dataset id
     hits = list(merged.values())
     ```
   - **Installed convenience** — `scripts/search_expanded.py` does the fan-out, unions by `id`, reports
     exactly which terms it searched (so a broadened match is never mistaken for an exact-name hit), and
     adds fan-out caps plus the client's extra filters:
     ```bash
     # after the ols MCP expands "liver" -> liver, hepatic, hepatocyte:
     python scripts/search_expanded.py --terms "liver,hepatic,hepatocyte" --modality sequencing
     ```

**Precision guardrail — prune before you union.** Free-text `q=` is **OR-tokenized**: a multi-word term
matches on *any* of its tokens, and recall is dominated by its most generic word. `q="red blood cell"`
is really `red OR blood OR cell`, so it drags in every dataset whose text merely contains `cell` (e.g.
"Billion **Cell** Project") — false positives that masquerade as recall. This bites hardest with
**ancestors** (which resolve to broad terms) and any expansion term reduced to a generic single token.
So: search **single, specific tokens**; drop generic ones (`cell`, `blood`, `tissue`, `entity`); and
sanity-check a broadened hit by confirming the record text genuinely relates before trusting the count.

**Standalone fallback (no agent/MCP):** run with `--q` instead of `--terms` and the script expands the
term itself against the public OLS4 REST API — the same EBI service the MCP fronts — scoped with
`--ontology` (`uberon`/`cl`/`efo`/`mondo`) and any of `--children` (immediate subtypes), `--subtypes`
(full descendant subtree), `--ancestors` (broader terms; upper-ontology roots like `entity` are dropped
automatically, but still prune the remaining generic terms). If OLS is unreachable it warns and searches
the bare term. Use `--no-expand` to search verbatim.

```bash
python scripts/search_expanded.py --q liver --ontology uberon --children --ancestors   # self-expand, no MCP
```

Cap fan-out with `--max-terms` (default 8), and narrow with the same dataset filters as `catalog search`
(`--modality`, `--project`, `--organism`, `--tissue`, `--assay`, `--disease`, `--sub-modality`,
`--development-stage`, `--access-scope`, `--all-versions`). Full `ols` tool reference:
[reference/rest.md](reference/rest.md#manual-ols-expansion-finer-control-than-the-script).

## Other CLI commands

```bash
catalog facets --fields organism,tissue,assay        # discover the real filter vocabulary
catalog list --project CellXGene --modality imaging --limit 100
catalog lineage <dataset-uuid> --direction up --depth 3
catalog collections entries <collection-uuid>
```

`catalog facets` has no REST endpoint behind it — it is a `search` call with `facets=<field>` params,
reading the response's `facets`. There is no `/api/datasets/facets/`; the no-install recipe is in
[reference/rest.md](reference/rest.md).

Subcommands: `search`, `facets`, `get`, `list`, `lineage`, `collections`. Run `catalog <cmd> -h` for
flags. Prefer `catalog search` for plain queries and `search_expanded.py` when recall matters. The
equivalent SDK surface:

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

`CatalogClient(base_url, api_token, timeout=30.0)`; `AsyncCatalogClient` mirrors it under `async with`.
Sub-clients: `.datasets`, `.collections`, `.lineages`.

## Reference

- **[reference/install.md](reference/install.md)** — tagged-release install (CLI + SDK + scripts).
- **[reference/rest.md](reference/rest.md)** — direct REST, read-endpoint table, search-vs-list
  semantics and gotchas, full dataset record shape, pagination, and manual OLS expansion.
