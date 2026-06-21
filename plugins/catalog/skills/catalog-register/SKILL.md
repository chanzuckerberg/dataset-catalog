---
name: catalog-register
description: Map a user's existing dataset metadata onto the latest catalog schema and write a runnable registration script using catalog-client. Use when asked to map/convert/ingest dataset metadata, fit data to the dataset schema, build a DatasetRequest, populate experiment/sample/data_summary/channel fields, or write/generate a script to register/create/submit a dataset to the Scientific Dataset Catalog.
---

# Map data to the schema & write a registration script (catalog-client)

`catalog-client` is a Python SDK for the Scientific Dataset Catalog API. This
skill helps you take **metadata a user already has** (a CSV row, a LIMS export,
a JSON blob, a spreadsheet) and:

1. **map** each field onto the latest dataset schema (**v1.4.0**), then
2. **write a registration script** the user runs to `POST` it to the catalog.

There is no UI and no bundled server — registration is one HTTPS `POST` to a
remote catalog. This skill ships as part of the **`catalog`** plugin; the
bundled helper and schema reference are addressed via `${CLAUDE_PLUGIN_ROOT}`
(set automatically when the plugin loads) so they resolve wherever the plugin is
installed.

## The workflow

1. **See the live schema before mapping.** Don't trust memory or a doc that can
   drift — print the actual model tree (required fields marked `*`, blocks that
   accept extras marked `[extra=allow]`):
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/catalog-register/register_dataset.py" --fields
   ```
2. **Copy the template** `register_dataset.py` to a working file and edit two
   things: `load_source()` (point it at the user's data) and `build_request()`
   (the field mapping — one builder call per source field).
3. **Dry-run: validate + check coverage** — no token, no network:
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/catalog-register/register_dataset.py" --dry-run
   ```
   It validates with the same Pydantic rules the API enforces, prints the exact
   JSON payload, runs the full `register()` flow against an in-process fake
   catalog, **and reports coverage** — every source field that was mapped,
   explicitly dropped, or *silently lost*. Iterate until coverage is clean.
4. **Register for real** once the user has a token:
   ```bash
   export CATALOG_API_URL=https://your-catalog.example.com
   export CATALOG_API_TOKEN=...        # issue at <catalog>/docs -> /token/issue
   python "${CLAUDE_PLUGIN_ROOT}/skills/catalog-register/register_dataset.py" --submit
   ```

## The harness / template

[`register_dataset.py`](register_dataset.py) is both the **template** you give
the user and the **mapping harness** you run. Read `build_request()` first — it
is the worked mapping example (source dict → every v1.4.0 block). Three modes:

- `--fields` — print the live schema tree (authoritative; reads the pydantic
  models, so it never goes stale). Use it to find exact field names and which
  blocks accept extras.
- `--dry-run` — validate the mapping, print the payload, mock-submit, and report
  coverage. Verified output:
  ```
  [mapping valid] schema=v1.4.0  canonical_id=evican-brightfield-batch-01  locations=1
  { ...full JSON payload... }
  [dry-run submit OK] would register -> dataset_id placeholder 00000000-0000-4000-8000-000000000000
  [coverage] 24 mapped + 1 dropped of 25 source fields
    ✓ every source field is mapped or explicitly dropped
    metadata blocks populated: experiment, sample, data_summary
  ```
- `--submit` — register against the real catalog (needs the env vars above).

## Prerequisites

The helper imports `catalog_client`, which installing the plugin does **not**
provide. The Python interpreter that runs `register_dataset.py` must have it:

```bash
# inside the dataset-catalog monorepo (dev):
uv sync --all-groups          # then invoke with `uv run python ...`

# anywhere else (standalone):
pip install 'git+ssh://git@github.com/chanzuckerberg/dataset-catalog.git#subdirectory=dataset-catalog-client'
```

Field-level schema reference travels with the plugin at
`${CLAUDE_PLUGIN_ROOT}/skills/catalog-register/reference/dataset-schema.md`; the
`--fields` command prints the same schema live from the installed models.

## Mapping cheat-sheet (source field → schema slot → builder call)

`build_request()` in the template shows all of these in context. Required
blocks: `canonical_id`, `name`, `modality`, `locations` (≥1), `governance`,
`metadata`.

| User's data | Schema slot | Builder call |
|---|---|---|
| stable external id | `canonical_id` (signature) | `new_registration(canonical_id=...)` |
| version / project | `version`, `project` (signature) | `new_registration(version=..., project=...)` |
| modality | `modality` | `modality=DatasetModality(...)` — `imaging` / `sequencing` / `mass spec` / `unknown` |
| raw vs processed | `dataset_type` | `.of_type(DatasetType.raw)` (`raw` or `processed`) |
| file/folder URI + checksum | `locations[]` (signature fields) | `.with_location(uri, asset_type=..., storage_platform=..., checksum=..., checksum_alg=...)` |
| license / access / owner / PHI | `governance` | `.with_governance(license=..., access_scope="internal", data_owner=..., is_phi=...)` |
| assay / instrument / sub-modality | `metadata.experiment` | `.with_experiment(sub_modality=..., assay=[OntologyEntry(...)])` |
| organism / tissue / disease | `metadata.sample` | `.with_sample(organism=[OntologyEntry(...)], tissue=[TissueEntry(...)])` |
| cell/read counts, channels, dims | `metadata.data_summary` | `.with_data_summary(cell_count=..., channels=[ChannelMetadata(...)], ...)` |
| QC results | `data_quality` | `.with_data_quality(checks_passed=..., checks_failed=...)` |
| provenance link | lineage edge | `.with_lineage(source, lineage_type=LineageType...)` |

Ontology values are `OntologyEntry(label=..., ontology_id=...)`; tissue adds
`TissueEntry(..., type=...)`. Per-channel biology is
`ChannelMetadata(..., biological_annotation=BiologicalAnnotation(...))`.

## Extras — source fields with no exact slot

Don't drop a source field just because the schema has no named home for it.
**Every metadata block has
`extra="allow"`** (`DatasetMetadata`,
`ExperimentMetadata`, `SampleMetadata`, `DataSummaryMetadata`, `ChannelMetadata`,
… — confirm with `--fields`, look for `[extra=allow]`). Unknown keys are
preserved, not rejected. So:

- Field is *sample-ish* (e.g. `sex`, `ethnicity`, `donor_id`) → pass it as an
  extra kwarg to `.with_sample(...)`.
  - If that field names an **ontology concept** (`cell_line`, `cell_type`,
    `cell_strain`, `organelle`, …), give it the same shape as the named sample
    fields: a `list[OntologyEntry]` (`[OntologyEntry(label=..., ontology_id=...)]`),
    not a bare string. Resolve `ontology_id` via OLS (see playbook) just like
    `organism` / `tissue` / `disease`.
- Field is *measurement-ish* (e.g. `feature_count`, `mean_genes_per_cell`) →
  extra kwarg to `.with_data_summary(...)`.
- Field doesn't belong to `sample` / `experiment` / `data_summary` → put it
  under the single `additional_metadata` key on the metadata block via
  `.with_custom_metadata(additional_metadata={...})`. Keep everything that has
  no named slot together under that one key rather than scattering top-level
  custom keys.

**Exception — `governance` is fixed-shape.** Never route extras into
`.with_governance(...)`. Map only the schema's named fields (`license`,
`data_sensitivity`, `access_scope`, `is_pii`, `is_phi`, `data_steward`,
`data_owner`, `is_external_reference`, `embargoed_until`); a governance-ish
source field with no matching name goes under `.with_custom_metadata(...)`, not
into the governance block.

This is how you get **lossless** mappings. The coverage report exists to make
sure you made a *deliberate* choice for every field — mapped, extra, or
`src.drop(...)` — rather than losing it by omission.

## Mapping playbook (heuristics)

- **Read `--fields` first.** Map onto real field names; never guess
  (`ontology_id` not `ontology_term_id`, `type` not `tissue_type`).
- **Normalize, don't copy.** Source key names rarely match. Write small
  helpers (`_ontology()`, `_storage_platform()`) instead of inlining renames.
- **Infer the enums.** `modality` ∈ {`imaging`,`sequencing`,`mass spec`,`unknown`}
  and `dataset_type` ∈ {`raw`,`processed`} usually have to be *derived* from the
  source (assay type, file format, processing stage), not copied verbatim.
- **Don't invent values.** If the source has no `license`/`checksum`/owner,
  leave it unset — empty is honest; a fabricated value is a data-quality bug.
- **`access_scope` is always `"internal"`.** Hard-code it in `.with_governance(...)`;
  never map it from a source `visibility`/`public` field.
- **Never assume `is_pii` / `is_phi`.** Both default to `None` (unknown) — do
  **not** default them to `False` when the source is silent. Always confirm the
  PII and PHI status with the user before setting either.
- **Confirm `storage_platform` when it isn't obvious.** Don't infer it from the
  path alone. A `/hpc/...` path is **not** always `sf_hpc` — there are three HPC
  backends (`sf_hpc`, `chi_hpc`, `ny_hpc`); ask which site. An `http(s)://` URI
  is **not** always `external` — internal platforms can sit behind a URL. State
  your assumption and confirm with the user before mapping. (Members: `s3`,
  `sf_hpc`, `chi_hpc`, `ny_hpc`, `reef`, `kelp`, `external`, `other`.)
- **Resolve ontology labels via OLS.** When an ontology field gives only a
  `label` and no id, look the term up in the EBI Ontology Lookup Service and use
  the returned CURIE as `ontology_id` (e.g. `Homo sapiens` → `NCBITaxon:9606`):
  `GET https://www.ebi.ac.uk/ols4/api/search?q=<label>&exact=true` — take the
  top hit's `obo_id`/`curie` from the matching ontology. Don't fabricate ids;
  if OLS returns no confident match, leave `ontology_id` unset and keep the label.
- **Zarr paths: confirm granularity first.** When a data path is a `.zarr` store,
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
  `project/screen/plate/well/fov`, not reversed or `_`-joined). Use the same
  ordering for every record so ids sort and group sensibly.
- **Keep signatures stable across re-runs.** `canonical_id` + `version` +
  `project` + each asset's signature fields define identity; pick them from
  stable source IDs so re-running updates rather than duplicates.
- **Coverage must be clean before `--submit`.** Resolve every "SILENTLY LOST"
  field. If a field truly shouldn't be carried, `src.drop(...)` it so the
  decision is explicit and visible to the next person.

## Registering — the call the script makes

`.submit()` runs a duplicate check (GET `/api/datasets/` on the signature) then
creates (POST `/api/datasets/`), returning the new `dataset_id`. Flags:

- `submit(error_on_duplicate=False)` — return the existing id instead of raising `DuplicateDatasetError`.
- `submit(update_if_exists=True)` — PATCH the existing record. Mutually exclusive with `error_on_duplicate=True`.

Get a token from the catalog's `/docs` → Token → `/token/issue`. Pass it via the
`CATALOG_API_TOKEN` env var; never hard-code it.

## Test (monorepo dev only)

The skill source lives in the `dataset-catalog` monorepo under
`plugins/catalog/`. To exercise the client it maps onto:

```bash
cd dataset-catalog-client && uv run pytest -q   # 207 passing
```

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
  exists; use `error_on_duplicate=False` or `update_if_exists=True`.
- `AuthenticationError` (401) → bad/expired token; reissue at `/token/issue`.
