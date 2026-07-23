---
name: catalog-read
description: Read and analyze the Scientific Dataset Catalog (read-only) — get a dataset by UUID or canonical ID, list a project, browse collections, discover facet values, trace lineage, and aggregate, summarize, compare, or visualize across results. This is the everyday default for known-item lookups and bounded reads. For high-recall search that expands a term through synonyms and the ontology hierarchy, use catalog-search instead.
allowed-tools: Bash, Read, Write, Skill, Task
---

# Read and analyze the Scientific Dataset Catalog

**Read-only contract: `GET` only against the Catalog; the token stays in the env
header; keep raw output out of the conversation.** The full contract lives in
`${CLAUDE_PLUGIN_ROOT}/reference/read-contract.md` — load it first (lifecycle
step 1).

## Role and authority

You perform read-only reads and analyses and present distilled results to the
user. You **must not** create, update, delete, or register anything — that is the
`catalog-register` skill. You **must not** broaden a query with synonyms or
ontology terms here — that is `catalog-search` (see *Decision rules*).

## Execution lifecycle

1. **Load the operating contract** — read
   `${CLAUDE_PLUGIN_ROOT}/reference/read-contract.md` (credentials, preflight,
   prohibitions, output hygiene, completeness labeling) and run preflight.
2. **Classify the request** — known-item lookup, bounded list, or analysis.
3. **Choose the smallest suitable surface** (see *Tool selection*).
4. **State a one-line plan** for anything beyond a single known-item `GET`: the
   filters, the expected number of passes, and the pagination scope. Execute only
   that plan; do not widen it because a result looks sparse.
5. **Execute within the ceilings** below.
6. **Validate the result** — confirm filters actually narrowed the total.
7. **Present only the required output**, and **visualize** it if asked (below).
8. **Stop.** A small or empty result is a valid result.

## Source of truth

`${CLAUDE_PLUGIN_ROOT}/reference/rest.md` is authoritative for endpoints, filters,
pagination, facet behavior, and the dataset record shape. Read it before
constructing a call you are unsure of. This skill defines **workflow, limits,
output, and visualization** only. Installation of the optional CLI/SDK:
`${CLAUDE_PLUGIN_ROOT}/reference/install.md`.

## Execution ceilings

* Scan **at most 3 pages** per query inline. Beyond that, delegate to the
  `catalog-reader` subagent.
* Bring **at most ~50 rows** into the main conversation. A larger result set must
  be reduced (see *Analysis*) or delegated, never dumped.
* Page size max is 100; `limit > 100` returns HTTP 422.

When a ceiling is reached, return what you have, **labeled partial**, with the
exact limit named. A ceiling is a stopping point, not a trigger to escalate.

## Tool selection

Choose the least powerful surface that completes the task:

* **Direct REST** (Python standard library) — default for a bounded search, list,
  get, or facet call. No install; token stays in the environment. Pattern in
  `reference/rest.md`.
* **`catalog-reader` subagent** — when the result may span pages, the size is
  uncertain, or an analysis must scan many records. It runs the reads in its own
  context and returns only the distilled answer. Tell the user the scope first.
* **CLI / SDK** — only when already installed and their pagination or typed
  processing genuinely helps. Do **not** install software merely to perform a read.

## Decision rules

### Exact filter vs. escalate to search

Prefer an exact facet or list filter when the concept maps to a controlled value
(`organism`, `tissue`, `assay`, `modality`, `project`, `access_scope`, …); confirm
the stored value first (per *Detect silent failures* in the contract). If the
request needs **synonym breadth or ontology subtypes** — e.g. a dataset tagged
"hepatic" must surface for "liver" — **stop and use `catalog-search`**. Do not
attempt expansion here.

### Analysis: reduce before returning

Analysis means aggregating, summarizing, or comparing across many records
(distributions, coverage, cross-project comparison, dedup-then-count). Reduce the
data to its summary **before** it reaches the main conversation — delegate the
scan to the `catalog-reader` subagent and ask for the aggregate, or run a small
Python reduction over paginated results and print only the summary.

Never pull the full row set into context to compute a number from it. **Do not
blindly sum aggregate fields** — values like `data_summary.cell_count` may be
collection-level figures repeated on every constituent dataset; report per-dataset
values or deduplicate canonical datasets first.

## Visualization

When the user asks to visualize, chart, plot, or "show" an analysis — or when a
distribution, trend, or comparison reads far more clearly as a picture — turn the
**reduced** result into a visualization. Chart the summary, never the raw row set.

1. **Reduce first.** Compute the aggregate exactly as *Analysis* requires. The
   chart's input is that small summary table, not paginated JSON.
2. **Invoke the `dataviz` skill** *before* writing any chart code, choosing
   colors, or laying out a dashboard — it owns the palette, chart-type heuristic,
   and accessibility rules.
3. **Emit a self-contained artifact** — write an HTML/SVG file (or plotting
   script) to the working directory and tell the user the path. Writing a local
   chart file is permitted; the read-only contract governs the Catalog, not the
   filesystem.
4. **Label the population** the chart was computed over and its completeness
   (complete / partial / truncated), the same as any analysis result.

Pick the chart type from the data shape: categorical breakdown → bar; part-of-
whole → stacked bar (avoid pie beyond ~5 slices); trend over version or time →
line; two-facet cross-tab → grouped bar or heatmap. Do not chart a single number —
state it.

## Stopping conditions

Beyond the common stops in `read-contract.md`, stop and report when:

* the planned work exceeds a ceiling → report the scope and ask the user to
  authorize a larger scan (e.g. via the subagent).

## Final return checklist

* Did I stay read-only against the Catalog (`GET` only)?
* Did I execute only the stated plan, within every ceiling?
* Did I validate controlled values before filtering?
* Did I reduce before returning or charting, instead of dumping rows?
* If I visualized, did I invoke `dataviz` and label the population and completeness?
* Did I label partial or truncated results with the exact limit?
* Did I keep the token and raw output out of the conversation?
* Did I stop after producing the requested result?
