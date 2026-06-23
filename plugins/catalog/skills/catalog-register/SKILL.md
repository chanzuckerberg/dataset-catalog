---
name: catalog-register
description: Map a user's existing dataset metadata onto the latest catalog schema and write a runnable registration script using catalog-client. Use when asked to map/convert/ingest dataset metadata, fit data to the dataset schema, build a DatasetRequest, populate experiment/sample/data_summary/channel fields, or write/generate a script to register/create/submit a dataset to the Scientific Dataset Catalog.
---

# Map data to the schema & write a registration script (catalog-client)

`catalog-client` is a Python SDK for the Scientific Dataset Catalog API. This
skill takes **metadata a user already has** (a CSV row, a LIMS export, a JSON
blob, a spreadsheet) and (1) **maps** each field onto the **current** dataset
schema — the version marked `Current` in the `schema/` folder on GitHub,
overlaid with the installed client's models (step 1 below) — then (2) **writes a
registration script** the user runs to `POST` it to the catalog. Registration is
one HTTPS `POST` to a remote catalog — no UI, no bundled server. Don't hard-code
a version (e.g. "v1.4.0"); resolve it from the schema folder each time.

## Workflow

[`register_dataset.py`](register_dataset.py) is both the **template** you hand
the user and the **harness** you run; read `build_request()` first — it's the
worked example (source dict → every schema block). Paths below use
`$P=${CLAUDE_PLUGIN_ROOT}/skills/catalog-register` (set when the plugin loads).

1. **Pull the current schema from GitHub, then overlay the live client.** Two
   layers, in order:
   - **GitHub (semantics + which version is current).** Fetch
     `https://raw.githubusercontent.com/chanzuckerberg/dataset-catalog/main/schema/README.md`
     and read its *Versions* table — the row marked **Current** is the schema
     version to register against (do **not** hard-code one; it changes). Then
     fetch that version's doc,
     `https://raw.githubusercontent.com/chanzuckerberg/dataset-catalog/main/schema/<version>/schema.md`,
     for the authoritative field-level definitions and meanings.
   - **Installed client (what actually validates).** Overlay the GitHub doc with
     `python $P/register_dataset.py --fields` (next step) — the live pydantic
     models. The GitHub doc tells you what each field *means* and which version
     is current; `--fields` is what the payload is validated against at
     `--dry-run`. **The installed client wins on any conflict:** if its
     `record_schema_version` default differs from the GitHub `Current` row, the
     client is stale — upgrade/reinstall it (step in Prerequisites) so the two
     agree before mapping. A static copy of one version travels offline at
     `$P/reference/dataset-schema.md`, but GitHub is the source of truth for
     *which* version is current.
2. **See the live schema** — `python $P/register_dataset.py --fields`.
   Reads the pydantic models, so it never goes stale; required fields are marked
   `*`, blocks accepting extras `[extra=allow]`. Map onto these exact names.
3. **Copy the template** to a working file; edit only `load_source()` (point at
   the data) and `build_request()` (one builder call per source field).
4. **Dry-run** (no token, no network) — `python $P/register_dataset.py --dry-run`.
   Validates with the API's own Pydantic rules, prints the JSON payload,
   mock-submits against an in-process fake catalog, and reports **coverage** —
   every source field mapped, dropped, or *silently lost*. Iterate until clean:
   ```
   [mapping valid] schema=v1.4.0  canonical_id=evican-brightfield-batch-01  locations=1
   [coverage] 24 mapped + 1 dropped of 25 source fields
     ✓ every source field is mapped or explicitly dropped
   ```
5. **Submit** once the user has a token (issue at `<catalog>/docs -> /token/issue`):
   ```bash
   export CATALOG_API_URL=https://your-catalog.example.com CATALOG_API_TOKEN=...
   python $P/register_dataset.py --submit
   ```

## Prerequisites

`register_dataset.py` imports `catalog_client`, which the plugin does **not**
install — the interpreter that runs it must already have it.

**Before any `pip install`, ask the user whether to use a virtual environment,
and create one if they agree.** Don't install into the system/global interpreter
silently. Default to recommending a venv; only skip it if the user declines or is
already inside an activated venv / the monorepo's managed environment.

**Install a tagged release, never `main`.** Resolve the latest released
`catalog-client` tag first (releases are tagged `catalog-client-v<X.Y.Z>`), then
install that exact tag — `main` is unreleased and may not match any published
schema version:

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
pip install "git+ssh://git@github.com/chanzuckerberg/dataset-catalog.git@${TAG}#subdirectory=dataset-catalog-client"
```

To upgrade a stale client so its `record_schema_version` matches the GitHub
`Current` row (step 1), re-resolve `$TAG` and re-run the install with `--upgrade`
inside the same venv. If the newest release still lags the `Current` schema, the
release hasn't shipped yet — register against the installed release's version and
flag the gap to the user rather than installing from `main`.

`--fields` is the authoritative *runtime* schema (live from the installed
models); the GitHub `schema/` folder (step 1) is authoritative for which version
is current. A static copy travels at `$P/reference/dataset-schema.md` for offline
reference.

## Mapping cheat-sheet (source field → schema slot → builder call)

`build_request()` in the template shows all of these in context. Required
blocks: `canonical_id`, `name`, `modality`, `locations` (≥1), `governance`,
`metadata`.

| User's data                                       | Schema slot | Builder call |
|---------------------------------------------------|---|---|
| stable external id                                | `canonical_id` (signature) | `new_registration(canonical_id=...)` |
| version / project                                 | `version`, `project` (signature) | `new_registration(version=..., project=...)` |
| modality                                          | `modality` | `modality=DatasetModality(...)` — `imaging` / `sequencing` / `mass spec` / `unknown` |
| raw vs processed                                  | `dataset_type` | `.of_type(DatasetType.raw)` (`raw` or `processed`) |
| file/folder URI + checksum                        | `locations[]` (signature fields) | `.with_location(uri, asset_type=..., storage_platform=..., checksum=..., checksum_alg=...)` |
| license / access / owner / PHI                    | `governance` | `.with_governance(license=..., access_scope="internal", data_owner=..., is_phi=...)` |
| assay / instrument / sub-modality                 | `metadata.experiment` | `.with_experiment(sub_modality=..., assay=[OntologyEntry(...)])` |
| organism / tissue / disease / developmental_stage | `metadata.sample` | `.with_sample(organism=[OntologyEntry(...)], tissue=[TissueEntry(...)])` |
| cell/read counts, channels, dims                  | `metadata.data_summary` | `.with_data_summary(cell_count=..., channels=[ChannelMetadata(...)], ...)` |
| QC results                                        | `data_quality` | `.with_data_quality(checks_passed=..., checks_failed=...)` |
| provenance link                                   | lineage edge | `.with_lineage(source, lineage_type=LineageType...)` |

Ontology values are `OntologyEntry(label=..., ontology_id=...)`; tissue adds
`TissueEntry(..., type=...)`. Per-channel biology is
`ChannelMetadata(..., biological_annotation=BiologicalAnnotation(...))`.

## Extras — source fields with no exact slot

Don't drop a source field just because the schema has no named home for it.
**Every metadata block has
`extra="allow"`** (`DatasetMetadata`,
`ExperimentMetadata`, `SampleMetadata`, `DataSummaryMetadata`
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
- **Don't invent values.** If the source has no `checksum`/owner, leave it
  unset — empty is honest; a fabricated value is a data-quality bug.
- **`license`: ask, don't guess.** If you can't find license information in the
  source, check with the user what it should be rather than leaving it blank or
  fabricating one. Only set `license` to a value the user confirms.
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
  `dataset/screen/plate/well/fov`, not reversed or `_`-joined). Use the same
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
