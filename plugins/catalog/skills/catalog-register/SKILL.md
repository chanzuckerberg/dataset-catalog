---
name: catalog-register
description: Maps a user's dataset metadata onto the latest catalog schema and creates a runnable registration script. Use when asked to map/convert/ingest dataset metadata, fit data to the dataset schema, populate experiment/sample/data_summary/channel fields, or create a script to register/submit a dataset to the Scientific Dataset Catalog.
---

# Register datasets to the Scientific Dataset Catalog

`catalog-client` is a Python SDK for the Scientific Dataset Catalog API.
Takes **metadata a user already has** (CSV row, LIMS export, JSON blob, spreadsheet) and produces a **script** that:

1. **Maps** each field onto the **current** dataset schema, version marked `Current` in `schema/` on GitHub, overlaid with installed client models.
2. **Writes a registration script** the user runs to register to the catalog.

Registration is an HTTPS call to a remote catalog. No UI. No bundled server.

## Prerequisites

### 1. Python Environment
- Before any `pip install` or python command: ask user whether to use a virtual environment. Create one if they agree.
- Never install into system/global interpreter silently.
- Default: recommend venv. Skip only if user declines or already inside activated venv / monorepo managed environment.

### 2. catalog client dependency
- `scripts/register_dataset.py` imports `catalog_client` not installed by plugin. Interpreter must already have it.

- **Install a tagged release, never `main`.** Resolve latest released `catalog-client` tag first (tagged `catalog-client-v<X.Y.Z>`), then install that exact tag. `main` is unreleased and may not match any published schema version:

```bash
# resolve the latest released tag (requires the gh CLI):
TAG=$(gh release list --repo chanzuckerberg/dataset-catalog \
  --json tagName,publishedAt \
  --jq 'map(select(.tagName | startswith("catalog-client-v"))) | sort_by(.publishedAt) | reverse | .[0].tagName')
echo "latest release: $TAG"   # e.g. catalog-client-v0.3.0
```


```bash
# 1. monorepo dev — uv manages the environment for you (no manual venv needed):
uv sync --all-groups            # then run via `uv run python ...`

# 2. standalone — create + activate a venv FIRST, then install the tagged release:
python -m venv .venv            # or: uv venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install "git+https://github.com/chanzuckerberg/dataset-catalog.git@${TAG}#subdirectory=dataset-catalog-client"
```

### Client vs schema version mismatch
To upgrade stale client so `record_schema_version` matches GitHub `Current` row (step 1): re-resolve `$TAG`, re-run install with `--upgrade` in same venv.

If newest release still lags `Current` schema: release hasn't shipped yet. Register against installed release's version. Flag gap to user. Do not install from `main`.

`--fields` is the authoritative *runtime* schema (live from the installed
models); the GitHub `schema/` folder (step 1) is authoritative for which version
is current.


## Workflow

[`register_dataset.py`](scripts/register_dataset.py) is both the **template** to hand the user and the **harness** to run.

Read `build_request()` first: worked example (source dict → every schema block).

Paths below use `$P=${CLAUDE_PLUGIN_ROOT}/skills/catalog-register` (set when the plugin loads).

1. **Pull the current schema from GitHub, then overlay the live client.** Two
   layers, in order:
   - **GitHub (semantics + which version is current).** Fetch
     `https://raw.githubusercontent.com/chanzuckerberg/dataset-catalog/main/schema/README.md`
     and read its *Versions* table — the row marked **Current** is the schema
     version to register against. Then fetch that version's doc,
     `https://raw.githubusercontent.com/chanzuckerberg/dataset-catalog/main/schema/<version>/schema.md`,
     for the authoritative field-level definitions and meanings.
   - **Installed client (what actually validates).** Overlay the GitHub doc with
     `python $P/scripts/register_dataset.py --fields` (next step) — the live pydantic
     models. The GitHub doc tells you what each field *means* and which version
     is current; `--fields` is what the payload is validated against at
     `--dry-run`. **The installed client wins on any conflict:** if its
     `record_schema_version` default differs from the GitHub `Current` row, the
     client is stale — upgrade/reinstall it (step in Prerequisites) so the two
     agree before mapping.
2. **See the live schema** — `python $P/scripts/register_dataset.py --fields`.
   Reads the pydantic models, so it never goes stale; required fields are marked
   `*`, blocks accepting extras `[extra=allow]`. Map onto these exact names.
3. **Copy the template** to a working file; edit only `load_source()` (point at
   the data) and `build_request()` (one builder call per source field).
4. **Dry-run** (no token, no network) — `python $P/scripts/register_dataset.py --dry-run`.
   Validates with the API's own Pydantic rules, prints the JSON payload,
   mock-submits, and reports **coverage** — every source field mapped, dropped, or *silently lost*. Iterate until clean:
   ```
   [mapping valid] schema=v1.4.0  canonical_id=evican-brightfield-batch-01  locations=1
   [coverage] 24 mapped + 1 dropped of 25 source fields
     ✓ every source field is mapped or explicitly dropped
   ```
5. **Submit** once the user has a token (issue at `<catalog>/docs -> /token/issue`):
   ```bash
   export CATALOG_API_URL=https://your-catalog.example.com CATALOG_API_TOKEN=...
   python $P/scripts/register_dataset.py --submit
   ```

## Mapping cheat-sheet (source field → schema slot → builder call)

`build_request()` in the template shows all of these in context. Required
blocks: `canonical_id`, `name`, `modality`, `locations` (≥1), `governance`,
`metadata`.

| User's data                                       | Schema slot | Builder call                                                                                             |
|---------------------------------------------------|---|----------------------------------------------------------------------------------------------------------|
| stable external id                                | `canonical_id` (signature) | `new_registration(canonical_id=...)`                                                                     |
| version / project                                 | `version`, `project` (signature) | `new_registration(version=..., project=...)`                                                             |
| modality                                          | `modality` | `modality=DatasetModality(...)` — `imaging` / `sequencing` / `mass spec` / `unknown`                     |
| raw vs processed                                  | `dataset_type` | `.of_type(DatasetType.raw)` (`raw` or `processed`)                                                       |
| file/folder URI + checksum /  size                | `locations[]` (signature fields) | `.with_location(uri, asset_type=..., storage_platform=..., checksum=..., checksum_alg=..., size_bytes=)` |
| license / access / owner / PHI / PII              | `governance` | `.with_governance(license=..., access_scope="internal", data_owner=..., is_phi=..., is_pii=...)`         |
| assay / instrument / sub-modality                 | `metadata.experiment` | `.with_experiment(sub_modality=..., assay=[OntologyEntry(...)])`                                         |
| organism / tissue / disease / developmental_stage | `metadata.sample` | `.with_sample(organism=[OntologyEntry(...)], tissue=[TissueEntry(...)])`                                 |
| cell/read counts, channels, dims                  | `metadata.data_summary` | `.with_data_summary(cell_count=..., channels=[ChannelMetadata(...)], ...)`                               |
| QC results                                        | `data_quality` | `.with_data_quality(checks_passed=..., checks_failed=...)`                                               |
| provenance link                                   | lineage edge | `.with_lineage(source, lineage_type=LineageType...)`                                                     |

- Ontology values are `OntologyEntry(label=..., ontology_id=...)`;
- tissue adds `TissueEntry(..., type=...)`.
- Per-channel biology is `ChannelMetadata(..., biological_annotation=BiologicalAnnotation(...))`.

## Extras: source fields with no exact slot

1. Don't drop a source field just because the schema has no named slot. Unknown keys are preserved, not rejected.
   **Most metadata blocks have `extra="allow"`**; confirm with `--fields` (look for `[extra=allow]`).
   - `DatasetMetadata`
   - `ExperimentMetadata`
   - `SampleMetadata`
   - `DataSummaryMetadata`

2. **Sample information**: field is about sample (e.g. `sex`, `ethnicity`, `donor_id`): pass as extra kwarg to `.with_sample(...)`.
   - If field names an **ontology concept** (`cell_line`, `cell_type`, `cell_strain`, `organelle`, …): give it same shape as named sample fields: `list[OntologyEntry]` (`[OntologyEntry(label=..., ontology_id=...)]`), not bare string.
   - Resolve `ontology_id` with `ols` MCP server (`searchClasses`; see playbook), same as `organism` / `tissue` / `disease`.

3. **Data Summary**: Field provides *measurement* on the data (e.g. `feature_count`, `mean_genes_per_cell`) → extra kwarg to `.with_data_summary(...)`.
4. **Experiment**: Field describes the experiment (e.g. `assay_target`, `instrument_model`) → extra kwarg to `.with_experiment(...)`.
5. Field doesn't belong to `sample` / `experiment` / `data_summary` → put it under the single `additional_metadata` key on the metadata block via
  `.with_custom_metadata(additional_metadata={...})`.
   - Keep everything that has no named slot together under that one key rather than scattering top-level custom keys.

### Exception
1. `governance` is fixed-shape. Never route extras into `.with_governance(...)`.
   - Map only the schema's named fields (`license`, `access_scope`, `is_pii`, `is_phi`,
      `data_steward`, `data_owner`, `is_external_reference`, `embargoed_until`);
   - **Skip `data_sensitivity`.** It is a named governance field, but leave it unset — do not map a source value onto it, and do not route it to `.with_custom_metadata(...)` either.
   - A source field about access, licensing, ownership, compliance, or data
     sensitivity (e.g. `confidentiality`, `usage_restrictions`, `data_use_agreement`,
     `consent`, `retention_policy`) that does **not** match one of the named fields
     above goes into `.with_custom_metadata(...)`, not into the `governance` block.

Goal: **lossless** mappings. Coverage report ensures every field is a deliberate choice: mapped, extra, or `src.drop(...)`. No silent omissions.


## Mapping playbook (heuristics)

1. **Read `--fields` first.** Map onto real field names; never guess
  (`ontology_id` not `ontology_term_id`, `type` not `tissue_type`).
2. **Normalize, don't copy.** Source key names rarely match. Write small
  helpers (`_ontology()`, `_storage_platform()`) instead of inlining renames.
3. **Infer the enums.**
  - `modality` ∈ {`imaging`,`sequencing`,`mass spec`,`unknown`}
  - `dataset_type` ∈ {`raw`,`processed`} usually have to be *derived* from the source (assay type, file format, processing stage), not copied verbatim.
4. **Don't invent values.** If the source has no `checksum`/owner, leave it
unset — empty is honest; a fabricated value is a data-quality bug.
5. **`license`: ask, don't guess.** If you can't find license information in the
  source, check with the user what it should be rather than leaving it blank or
  fabricating one. Only set `license` to a value the user confirms.
6. **`access_scope` is always `"internal"`.** Hard-code it in `.with_governance(...)`; never map it from a source.
7. **Never assume `is_pii` / `is_phi`.** Both default to `None` (unknown) — do
  **not** default them to `False` when the source is silent. Always confirm the
  PII and PHI status with the user before setting either.
8. **Confirm `storage_platform` when it isn't obvious.** Don't infer it from the path alone.
   - A `/hpc/...` path is **not** always `sf_hpc` — there are three HPC
        backends (`sf_hpc`, `chi_hpc`, `ny_hpc`); ask which site.
   - An `http(s)://` URI is **not** always `external` — internal platforms can sit behind a URL.
   - State your assumption and confirm with the user before mapping. (Members: `s3`,
        `sf_hpc`, `chi_hpc`, `ny_hpc`, `reef`, `kelp`, `external`, `other`.) Validate this with the client.
9. **Resolve ontology labels via the OLS MCP server.** This plugin configures an MCP server named `ols` that points at the EBI Ontology Lookup Service, so its tools are available directly.
   - Don't shell out to `curl`/REST. When an ontology field gives only a `label` and no id, call the
     `ols` server's **`searchClasses`** tool (`query=<label>`, plus
     `ontologyId=<NCBITaxon|UBERON|EFO|...>` when you know the expected ontology to
     disambiguate; fall back to the generic `search` tool otherwise). Take the top
     match's CURIE as `ontology_id` (e.g. `Homo sapiens` → `NCBITaxon:9606`) only if the label is an exact match (case-insensitive) to the returned `label` or its `synonyms`.
   - If the `ols` server isn't connected skip this.
   - **Non-200 / error response from `ols`.** If a `searchClasses`/`search` call
     comes back as an error rather than a result set (HTTP 4xx/5xx, rate-limit
     `429`, timeout, or a malformed/empty body), treat it as *unresolved*, not as
     a reason to stop the whole mapping:
     - **Transient** (`429`, `5xx`, timeout): retry the same call **once**. If it
       still errors, give up on that label.
     - **Terminal** (`4xx` other than `429`, or an unparseable response): don't
       retry — the query or server is the problem, not luck.
     - In either case fall back to the next two rules: keep the source `label`,
       leave `ontology_id` unset, and **never** fabricate or partially guess a
       CURIE from a failed lookup.
     - Note the unresolved label to the user (e.g. in the coverage summary) so the
       gap is visible and they can supply the id by hand.
   - **Don't fabricate ids:** if no confident match comes back, leave `ontology_id`
     unset and keep the label.
10. **Zarr paths: confirm granularity first.** When a data path is a `.zarr` store,
  ask the user what level each *dataset record* should represent —
  screen / plate / well / FOV. If they choose a coarser level (e.g. plate), also
  ask whether each `location` (data asset) should point at the next level down
  (e.g. one location per well/FOV) rather than the whole store. Map `locations`
  accordingly — don't assume one dataset = one `.zarr` root.
- **`version` is never null.** It's a required signature field (`str`, not
  optional). If the source has no version, default it to `"1.0.0"` — use
  `src.get("release") or "1.0.0"`, never pass `None`.
- **Composite `canonical_id`: highest → lowest granularity, `/`-separated.**
  When no single stable id exists and you build one from multiple values, order
  the parts coarsest to finest and join with `/` (e.g.
  `dataset/screen/plate/well/fov`, not reversed or `_`-joined). Use the same
  ordering for every record so ids sort and group sensibly.
- **Keep signatures stable across re-runs.** `canonical_id` + `version` +
  `project` + each asset's signature fields define identity; pick them from
  stable source IDs so re-running updates rather than duplicates.
- **Coverage must be clean before `--submit`.** Resolve every "SILENTLY LOST"
  field. If a field truly shouldn't be carried, `src.drop(...)` it so the
  decision is explicit and visible to the user.

## Registering — the call the script makes
`.submit()` runs duplicate check (GET `/api/datasets/` on signature) then creates (POST `/api/datasets/`), returning new `dataset_id`.

**Confirm duplicate-handling with user before `--submit`.** When record with same signature exists, `.submit()` behavior is controlled by `error_on_duplicate` (default `True`) and `update_if_exists` (default `False`). **Only one may be `True`; both raises `ValueError`.**

| Call | Behavior |
|------|----------|
| `submit()` | **error** — raise `DuplicateDatasetError`. Use when each run should be new record. |
| `submit(error_on_duplicate=False)` | **skip** — return existing id, no write. |
| `submit(error_on_duplicate=False, update_if_exists=True)` | **update** — PATCH existing record in place. |

Template's `submit_real()` calls `.submit()` with defaults. Edit that call to pass flags user chose.

Get token from catalog's `/docs` → Token → `/token/issue`. Pass via `CATALOG_API_TOKEN` env var. Never hard-code.


## Gotchas

- **Map onto the builder, then let it validate.** `--dry-run` calls
  `to_dataset_request().model_dump()` — the same Pydantic validation the API
  runs. A bad mapping (missing required block, wrong enum, wrong type) fails
  here with a precise error, before any network call.
- **`record_schema_version` is auto-set.** Don't map a source field
  onto it; the model defaults it.
- **`dataset_type` values are `raw` / `processed`** (`DatasetType.raw`) — not `primary`.
- **`data_quality.checks_*` accept any shape** (`Any`): a count, a list of
  names, or a nested dict all validate.
- **`extra="allow"` cuts both ways.** Unknown keys are preserved (great for
  lossless mapping) — but a *typo* in a real field name (`cell_cout=...`) is
  silently kept as an extra instead of raising. After `--dry-run`, eyeball the
  printed payload: a value that landed at the wrong nesting level is a typo'd
  field name. Cross-check names against `--fields`.
- **`with_experiment` / `with_sample` / `with_data_summary` fully replace**
  their block — calling one twice discards the first. Map everything for a block
  in a single call (e.g. build the whole `channels=[...]` list at once).
- **Signature fields define identity.** Changing `canonical_id`, `version`,
  `project`, or any asset `location_uri` / `asset_type` / `size_bytes` /
  `checksum` / `checksum_alg` tombstones the old record and mints a new UUID.
  Map them carefully and consistently across re-runs.
- **No live server on a clean machine.** `--dry-run` swaps the client's internal
  `_http` for an `httpx.MockTransport` fake catalog (`_mock_client` in the
  template) so you can validate the full submit path without a token.

## Troubleshooting

- `KeyError` / `None` in `build_request` → your source data is missing a field
  the mapping assumes; use `src.get("x")` for optional fields.
- `ValidationError: ... Field required` on `--dry-run` → a required block
  (`governance`, `metadata`, ≥1 `locations`) wasn't mapped.
- `ValueError: 'x' is not a valid DatasetModality` → map the source value to a
  valid enum member (`imaging` / `sequencing` / `mass spec` / `unknown`).
- `DuplicateDatasetError` on `--submit` → a dataset with the same signature
  exists; confirm intent with the user, then pass `error_on_duplicate=False` to
  skip (return the existing id) or `error_on_duplicate=False, update_if_exists=True`
  to update it in place (see *Registering*).
- `ValueError: update_if_exists and error_on_duplicate cannot both be True` →
  both flags were set; `update_if_exists=True` requires `error_on_duplicate=False`.
- `AuthenticationError` (401) → bad/expired token; reissue at `/token/issue`.
