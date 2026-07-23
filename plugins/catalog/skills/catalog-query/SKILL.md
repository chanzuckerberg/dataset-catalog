---
name: catalog-query
description: Read-only querying of the Scientific Dataset Catalog. Use for dataset search, dataset lookup by UUID or canonical ID, project listings, facet discovery, collection browsing, ontology-broadened search, and lineage tracing.
allowed-tools: Bash, Read
---

# Query the Scientific Dataset Catalog

Use this skill for read-only Catalog operations:

* search datasets
* get a dataset by UUID or canonical ID
* list project datasets
* discover facet values
* browse collections
* trace lineage
* broaden biological searches with ontology terms

Use direct REST for ordinary reads. It uses Python’s standard library and requires no installation.

Use the CLI, SDK, or bundled scripts only when their conveniences help.

## 1. Run preflight

Before querying, run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/preflight.py"
```

Use `--no-ping` only when the network check should be skipped.

The script verifies:

* the Catalog base URL
* that `CATALOG_API_TOKEN` is set
* that the token successfully authenticates

Exit code `0` means ready. Exit code `2` explains what must be fixed.

If the token is missing or expired, open the token page in the user’s logged-in browser:

```bash
BASE="${CATALOG_API_URL:-https://datacatalog.prod-sci-data.prod.czi.team}"
open "${BASE%/}/tokens"
```

Use `xdg-open` on Linux or `start ""` on Windows.

Ask the user to save the token in the Claude Code `settings.json` environment block. Do not ask them to paste it into chat, and never place it directly in a command.

## 2. Choose the smallest useful surface

### Direct REST

Default for bounded search, list, get, and facet calls.

* no installation
* token remains in the environment
* best for one or a few calls

See [reference/rest.md](reference/rest.md) for endpoints, filters, pagination, response shapes, and API gotchas.

### `catalog-reader` subagent

Default when the operation may require multiple calls or pagination.

Delegate:

* searches that may span pages
* project or collection listings
* facet discovery involving several fields
* ontology-expanded searches
* lineage traversal
* client-side filtering
* any query whose result size is uncertain

Run inline only for a clearly bounded call, such as fetching one known UUID.

Before delegating, tell the user what is being searched and the expected scope. When the agent returns, lead with the total number of matches.

### CLI, SDK, and scripts

Use when helpful:

* `catalog` for terminal-oriented lookups
* `catalog_client` for typed Python processing
* `search_expanded.py` for ontology expansion, fan-out, union, and match reporting
* `ols.py` for distilled OLS term lookup and hierarchy expansion

The scripts can use standard-library REST when the client package is absent. Do not install the package merely to perform a read.

Installation instructions are in [reference/install.md](reference/install.md). Install a tagged release, never `main`.

## 3. Choose facet filtering or free-text search

Before broadening a term, decide whether it belongs to a controlled facet.

Common facet dimensions include:

* `organism`
* `tissue`
* `assay`
* `disease`
* `sub_modality`
* `development_stage`
* `modality`
* `project`
* `access_scope`

### Prefer a facet when the concept fits one

For example:

* “blood” may be a tissue
* “10x” may be an assay
* “sequencing” is a modality

First retrieve the facet buckets and confirm the exact stored value:

```python
     # api_get is the doseq=True helper from Quick start
     api_get("/api/datasets/search/", facets=["tissue", "modality"], limit=1)["facets"]
```
Facet parameters are exact controlled values. Do not assume that an OLS synonym or subtype is a valid facet value.

Do not repeat the same concept in both a facet and `q`.

Bad:

```python
api_get("/api/datasets/search/", tissue="blood", q="blood",)
```

The `q` condition adds a second text requirement and can remove valid facet matches.

Good:

```python
api_get("/api/datasets/search/", tissue="blood")
```

Use `q` alongside a facet only when it represents a different concept.

### Use free text when facets are insufficient

Use free-text expansion when:

* the concept is not a facet
* the facet vocabulary lacks needed synonyms
* subtypes must be searched separately
* a facet-only query under-recognizes the intended concept

## 4. Broaden biological free-text searches

Prefer the bundled `ols.py` handler. It returns compact term information and can run inside the `catalog-reader` subagent.

Start by resolving the term:

```bash
python scripts/ols.py search liver --ontology uberon
```

Available expansion types:

```bash
python scripts/ols.py children <ontology-id>
python scripts/ols.py descendants <ontology-id>
python scripts/ols.py ancestors <ontology-id>
```

Use them as follows:

* `search`: preferred label and synonyms; always start here
* `children`: immediate, closely related subtypes
* `descendants`: the complete subtype subtree
* `ancestors`: broader terms, only for highly specific starting concepts

Scope to a known ontology when possible:

* `uberon`
* `cl`
* `efo`
* `mondo`

### Search each term separately

Run one Catalog search per retained term, then union results by dataset `id`.

```python
terms = ["liver", "hepatic", "hepatocyte"]
merged = {}

for term in terms:
    response = api_get(
        "/api/datasets/search/",
        q=term,
        modality="sequencing",
        limit=100,
    )

    for hit in response["results"]:
        merged.setdefault(hit["id"], hit)

hits = list(merged.values())
```

For automated expansion and union:

```bash
python scripts/search_expanded.py \
  --terms "liver,hepatic,hepatocyte" \
  --modality sequencing
```

The script may also expand a starting term itself:

```bash
python scripts/search_expanded.py \
  --q liver \
  --ontology uberon \
  --children
```

Useful controls include:

```text
--children
--subtypes
--ancestors
--max-terms
--no-expand
```

Tell the user which terms were searched.

### Prune generic terms

Catalog free-text search is OR-tokenized. A query such as:

```text
red blood cell
```

may match records containing any of:

```text
red OR blood OR cell
```

Prefer specific terms and remove generic tokens such as:

```text
cell
blood
tissue
entity
```

Ancestor expansion is especially likely to introduce overly broad terms. Inspect and prune expanded terms before trusting aggregate counts.

Use the OLS MCP only when `ols.py` cannot provide the required hierarchy or semantic-neighbor operation.

## 5. CLI and SDK examples

CLI:

```bash
catalog search --query liver --modality sequencing
catalog facets --fields organism,tissue,assay
catalog list --project CellXGene --limit 100
catalog lineage <dataset-uuid> --direction up --depth 3
catalog collections entries <collection-uuid>
```

SDK:

```python
import os
from catalog_client import CatalogClient

with CatalogClient(
    base_url=os.environ["CATALOG_API_URL"],
    api_token=os.environ["CATALOG_API_TOKEN"],
) as catalog:
    hits = catalog.datasets.search(
        q="liver",
        modality="sequencing",
        limit=10,
    )

    datasets = catalog.datasets.list(
        project="CellXGene",
        is_latest=True,
        limit=100,
    )

    dataset = catalog.datasets.get(dataset_id)
```

## References

* [reference/rest.md](reference/rest.md): routes, filters, facets, pagination, record shape, and manual OLS behavior
* [reference/install.md](reference/install.md): tagged-release installation for the CLI and SDK
