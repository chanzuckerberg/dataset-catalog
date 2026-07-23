---
name: catalog-search
description: Advanced high-recall search of the Scientific Dataset Catalog. Expands a term through its synonyms and the OLS ontology hierarchy, runs one search per term, and unions the results by dataset id to round up matches a single query misses (a dataset tagged "hepatic" will not surface for q=liver). Higher overhead than catalog-read — use when recall matters. For plain lookups, bounded lists, or analysis, use catalog-read instead.
allowed-tools: Bash, Read
---

# High-recall search of the Scientific Dataset Catalog

**Read-only contract: `GET` only against the Catalog and OLS; the token stays in
the env header; keep raw output out of the conversation.** The full contract lives
in `${CLAUDE_PLUGIN_ROOT}/reference/read-contract.md` — load it first (lifecycle
step 1).

## Role and authority

You perform recall-oriented search: resolve a concept to a set of related terms,
search each term, and union the hits by dataset `id`. This skill has **more
overhead** than `catalog-read` (multiple OLS lookups and one Catalog pass per
term) — use it only when a single query under-recalls the concept.

Two search-specific prohibitions beyond the shared contract:

* **Never** trust a union total built on a truncated pass (see *Execution
  ceilings*).
* **Never** add a term merely because the result count is low (see *Scope*).

## Execution lifecycle

1. **Load the operating contract** — read
   `${CLAUDE_PLUGIN_ROOT}/reference/read-contract.md` and run preflight.
2. **Confirm search is the right tool** — if the concept is an exact facet value
   or a known item, stop and use `catalog-read`.
3. **State a one-line plan** — the base term, the expansion relations
   (`synonyms` / `children` / `descendants` / `ancestors`), the filters, and the
   final term count after pruning. Execute only that plan; do not widen it because
   results look sparse.
4. **Resolve and expand** the term to a bounded set (below).
5. **Prune** generic terms before searching.
6. **Fan out and union** — one pass per term, merge by `id`.
7. **Present** the union with the exact terms searched (see *Output contract*).
8. **Stop.**

## Source of truth

`${CLAUDE_PLUGIN_ROOT}/reference/rest.md` is authoritative for the search
endpoint, its parameters, facet behavior, pagination, and the **OLS tool table and
expansion mechanics** (the "how"). This skill defines **when to expand, which
relations to use, how to prune, and what to return** (the "policy").

## Execution ceilings

* Search **at most 8 terms** after pruning. If the base term resolves to more,
  keep the most specific and drop the rest.
* Use **at most 1** facet-discovery request to confirm controlled values.
* Fetch a bounded page per term (`--limit`, default 25). If a pass **fills the
  limit exactly**, it is likely truncated and the union undercounts — raise the
  limit or narrow, and **label the total unverified** until it no longer fills.
* Multi-pass work belongs in the `catalog-reader` subagent; prefer delegating the
  whole fan-out rather than running many passes inline.

When a ceiling is reached, return the union collected so far, **labeled partial**,
naming the limit. A ceiling is a stopping point, not an escalation.

## Tool selection

Prefer the least powerful surface that gives the recall you need:

* **`ols.py`** (`${CLAUDE_PLUGIN_ROOT}/scripts/ols.py`) — **preferred** for term
  resolution and hierarchy walks. It prints distilled term rows, needs no install
  or token, and runs inside the `catalog-reader` subagent.

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ols.py" search liver --ontology uberon
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ols.py" children UBERON:0002107 --ontology uberon
  ```

  * `search` — preferred label and synonyms; always start here.
  * `children` — immediate subtypes. `descendants` — full subtree.
  * `ancestors` — broader terms; use **only** when the base term is already very
    specific, and prune aggressively (they lower precision).

* **`search_expanded.py`** (`${CLAUDE_PLUGIN_ROOT}/scripts/search_expanded.py`) —
  fan out and union in one call. Pass agent-resolved terms with `--terms`, or let
  it expand a single `--q` term itself. `--facet-union FIELD` searches each term as
  an exact facet value (more precise than free text); `--overlap-facet FIELD=VALUE`
  reports an exact "base + added" total instead of assuming the sets are disjoint.

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/search_expanded.py" \
    --terms "liver,hepatic,hepatocyte" --modality sequencing
  ```

* **`ols` MCP** — **last resort only**, for a semantic-neighbor search
  (`searchWithEmbeddingModel` / `getSimilarClasses`) or a `fetch` that `ols.py`
  does not expose. It returns the full OLS payload into context and **cannot** run
  inside the `catalog-reader` subagent.

## Decision rules

### Facet-union vs. free-text union

Prefer `--facet-union` over an ontology dimension (e.g. `tissue`) when the
sub-terms are controlled values — exact facet matches are far more precise than
OR-tokenized free text. Use free-text `q=` union when the concept is not a facet or
the vocabulary lacks the needed synonyms.

### Prune generic terms (precision)

Catalog free-text search is **OR-tokenized**: `red blood cell` behaves like
`red OR blood OR cell` and produces false positives. Before searching, drop generic
single-word tokens such as `cell`, `blood`, `tissue`, `entity`. Ancestor expansion
is the most likely source of over-broad terms — inspect and prune it before
trusting any aggregate count.

```text
Correct (facets, precise):  --facet-union tissue --terms "liver,caudate lobe of liver"
Incorrect (generic tokens): --terms "cell,tissue,liver"
```

### Facet values are exact

An OLS synonym or subtype is not automatically a valid facet value. When using
`--facet-union`, confirm the field and its buckets from `reference/rest.md` or one
facet-discovery request first. If a term contributes 0 hits it may be a facet value
outside the vocabulary — report the observation rather than trusting the count.

## Retry and failure handling

* An OLS lookup that fails transiently (timeout, `5xx`, `429`) may be retried
  **once** with the same parameters. If it still fails, search the terms you have
  and note the gap. `ols.py` already degrades to the bare term on failure.
* Do **not** retry an authentication, validation, or not-found error with broader
  inputs.

## Scope — do not expand autonomously

A small result is a valid finding. Do **not** add synonyms, pull in ancestors,
raise the per-term limit, or search adjacent resources merely because the count is
low. Widen the search only when the user explicitly authorizes a larger scope.

## Stopping conditions

Beyond the common stops in `read-contract.md`, stop and report when:

* the concept is an exact facet value or known item → redirect to `catalog-read`.
* the planned term count exceeds the ceiling → report the scope and ask the user to
  authorize a wider sweep.

## Output contract

In addition to the shared output hygiene, present:

1. **The number of distinct datasets** in the union.
2. **The exact terms searched** (and, when relevant, per-term hit counts).
3. When `--overlap-facet` was used, the exact `base + added` breakdown.

## Completeness and caveats

Mark the union **unverified** whenever any pass filled its limit, and name the
limit reached (see *Completeness labeling* in `read-contract.md`). Never let a
truncated union read as an exact count.

## Final return checklist

* Did I stay read-only, and confirm search (not `catalog-read`) was the right tool?
* Did I execute only the stated plan, within the 8-term and pass ceilings?
* Did I prune generic tokens before searching?
* Did I flag any pass that filled its limit as unverified?
* Did I report the exact terms searched and the distinct-dataset count?
* Did I keep the token, raw OLS payloads, and raw output out of the conversation?
* Did I stop instead of autonomously broadening a low-count result?
