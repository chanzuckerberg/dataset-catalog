---
name: search
description: Finds data in the Scientific Dataset Catalog (read-only) — free-text and faceted search, exact listing by canonical_id/version/project, fetching a record, resolving a file or S3 path to its dataset, tracing lineage, browsing collections, and cursor pagination. Also the duplicate check before registering and the lookup of lineage parents. Use when asked to find, list, look up, or count datasets, or "is this already registered?".
model: sonnet
---

# Finding data

Every call here is a `GET`. Writing is `registration-script`'s job. The token travels only as the
`X-catalog-api-token` header, never in a URL, argument, or output. If a call returns 401, check
access with `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_auth.py"` (auth skill).

## Surfaces

- **`catalog` CLI** (installed with the client; install steps in `registration-script`). Table on a
  terminal, JSON when piped; `-o json` forces JSON. Reads `CATALOG_API_URL` and `CATALOG_API_TOKEN`.
  Exit codes: 0 ok, 1 other error, 2 usage/config, 3 auth (401), 4 not found, 5 server/network.
- **Stdlib REST** when the client is not installed; do not install software just to read:

  ```python
  import json, os, urllib.parse, urllib.request
  BASE = os.environ["CATALOG_API_URL"].rstrip("/")
  H = {"X-catalog-api-token": os.environ["CATALOG_API_TOKEN"]}
  qs = urllib.parse.urlencode({"q": "liver", "limit": 10}, doseq=True)
  with urllib.request.urlopen(urllib.request.Request(f"{BASE}/api/v1/datasets/search/?{qs}", headers=H)) as r:
      page = json.load(r)
  ```

- **SDK** (`client.datasets.search / iter_search / list / iter_all / get / resolve / iter_resolve`,
  `client.lineages.list`, `client.collections.list_entries / list_parents`) inside scripts.

Plugin hooks auto-approve the CLI reads and stdlib GETs to catalog hosts.

## Which call

| Question | CLI | REST (`/api/v1/…`) |
|---|---|---|
| Free text + filters, ranked, with facet counts | `catalog search --q liver --organism "Homo sapiens"` | `GET datasets/search/` |
| What values does the catalog hold for a filter? | `catalog facets --fields tissue` | `GET datasets/search/?facets=tissue&limit=1` |
| Exact coordinates (canonical_id, version, project) | `catalog list --canonical-id X --project P` | `GET datasets/?canonical_id=X` |
| One full record | `catalog get <uuid>` or `catalog get <canonical_id> --version V --project P` | `GET datasets/{id}` |
| Which dataset holds this file or folder? | `catalog resolve s3://bucket/path/` | `GET datasets/resolve?uri=…` |
| Upstream / downstream | `catalog lineage <uuid> --direction up` | `GET lineage/?destination_dataset_id=…` / `?source_dataset_id=…` |
| Collections | `catalog collections list` / `entries <id>` / `parents <id>` | `GET collections/`, `collections/{id}/entries`, `…/parents` |
| Version history | — | `GET datasets/{id}/history` |

`datasets/{id}` takes the UUID, not the `canonical_id`; resolve coordinates through the list route first.

**Exact filters beat free text.** `q` is OR-tokenized: `red blood cell` matches `red OR blood OR cell`,
so multi-word terms return false positives. Prefer exact filters (`organism`, `tissue`, `assay`,
`modality`, `project`, …) after confirming the stored value with one facet request; never guess a
controlled value. `q` is also weak on projects that name datasets by accession: zero hits for a
descriptive phrase does not mean the data is absent, so retry once with filters plus facets. There
is no synonym or ontology expansion: search each term you mean.

## Duplicate checks and lineage parents (before registering)

1. `catalog resolve <uri>` for each data location: the most reliable duplicate check. Use
   `--scope ancestor` to find a dataset registered on a parent folder, `--scope descendant` for
   anything registered underneath. A bare POSIX path needs `--storage-platform` (every HPC site
   mounts its own `/hpc/projects/...`). On a deployment without the route the answer is
   `Dataset 'resolve' not found` (common-errors).
2. `catalog list --canonical-id X --version V --project P`: the signature lookup `register()` itself does.
3. There is no search by checksum; compare checksums on the records `resolve` returns.

For lineage parents, find the parent's UUID or its coordinates (`DatasetRef`) and confirm the exact
record with the user before it goes into `mapping.json`.

## Pagination and limits

| Route | Paging | Page size |
|---|---|---|
| `datasets/search/` | cursor only: pass `next_cursor` back as `cursor`; `null` means done | 1–1000 (1–100 with `hydrate=true`) |
| `datasets/` (list) | cursor, or `offset` up to 10000; not both | 1–500 |
| `datasets/resolve` | cursor only | 1–100 |
| `collections/*`, `lineage/`, `history` | `offset` + `limit` | 1–100 |

Keep filters and sort identical across a cursor walk. Walking the list route, sort `newest` or
`oldest` (immutable `created_at`); the default `last_modified` shifts under concurrent edits. The
SDK's `iter_search` / `iter_all` / `iter_resolve` manage cursors.

## Facets and fields

Facets come from the search route, repeated per field (`facets=organism&facets=tissue`, not
comma-joined; with `urlencode`, pass a list and `doseq=True`). Allowed facet fields are listed in the
422 for an unknown one. Buckets count only non-null values, so they can sum to less than `total`;
counts ignore `limit`. Search hits are lightweight; add `fields=locations` (or other fields),
`hydrate=true`, or fetch the record for full detail.

`incoming_lineage`, `outgoing_lineage`, and `collections` on a dataset are `null` unless you ask
(`--lineage` / `--collections`, or `include_lineage=true` / `include_collections=true`). Never
conclude "no lineage" from a response that left them off; an empty `lineage/` result is the real
answer. Edges carry ids only; fetch neighbours by id.

Domain metadata is nested: `metadata.experiment.*`, `metadata.sample.*`, `metadata.data_summary.*`,
`data_quality.*`, `governance.*`, `locations[].*` (field meanings: `field-reference`). Aggregates
such as `data_summary.cell_count` may repeat a collection-level value on each member: do not sum
them blindly. Tombstoned records are excluded unless you are auditing deletions.

## Answering

- Every dataset, id, owner, location, or count you report came back from the API in this session.
- Lead with the match count and the exact filters or terms. One compact row per dataset: `id`,
  `canonical_id`, `version`, plus only what was asked. Prefer `is_latest=true` unless a version was asked.
- Rank and recommend the best few; say when the top hit is weak. For data the user wants to use,
  include `access_scope`, owner or steward, and `locations` URIs.
- Keep raw JSON, facet dumps, and pagination bodies out of the conversation; summarize larger scans
  in a script and print only the result. Label a result partial when you stopped at a page limit.
- If the live API disagrees with this skill (a documented path 404s, a parameter 422s), read the
  current spec from `GET /api/v1/meta/openapi.json` with the token header and adapt; do not report
  the data as missing.
