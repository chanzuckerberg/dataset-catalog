---
name: model-and-register-dataset
description: Map a user's existing dataset metadata onto the latest catalog schema (v1.4.0) and write a runnable registration script using catalog-client. Use when asked to map/convert/ingest dataset metadata, fit data to the dataset schema, build a DatasetRequest, populate experiment/sample/data_summary/channel fields, or write/generate a script to register/create/submit a dataset to the Scientific Dataset Catalog.
---

# Map data to the schema & write a registration script (catalog-client)

`catalog-client` is a Python SDK for the Scientific Dataset Catalog API. This
skill helps you take **metadata a user already has** (a CSV row, a LIMS export,
a JSON blob, a spreadsheet) and:

1. **map** each field onto the latest dataset schema (**v1.4.0**), then
2. **write a registration script** the user runs to `POST` it to the catalog.

There is no UI and no bundled server — registration is one HTTPS `POST` to a
remote catalog. Paths below are relative to the package root
(`dataset-catalog/dataset-catalog-client/`).

## The workflow

1. **Get the user's source data and the schema in front of you.** Field
   reference: [`docs/dataset-model/dataset-schema.md`](../../../docs/dataset-model/dataset-schema.md)
   (authoritative, current as of v1.4.0).
2. **Copy the template** `register_dataset.py` (below) to a working file and
   edit two things: `load_source()` (point it at the user's data) and
   `build_request()` (the field mapping — one builder call per source field).
3. **Dry-run to validate the mapping** — no token, no network:
   ```bash
   uv run python .claude/skills/model-and-register-dataset/register_dataset.py --dry-run
   ```
   It validates with the same Pydantic rules the API enforces, prints the exact
   JSON payload, then exercises the full `register()` flow against an in-process
   fake catalog. Green = the mapping is wire-valid and submit works.
4. **Register for real** once the user has a token:
   ```bash
   export CATALOG_API_URL=https://your-catalog.example.com
   export CATALOG_API_TOKEN=...        # issue at <catalog>/docs -> /token/issue
   uv run python .claude/skills/model-and-register-dataset/register_dataset.py --submit
   ```

## The harness / template

[`register_dataset.py`](register_dataset.py) is both the **template** you give
the user and the **validation harness** you run. Read it first — `build_request()`
is the worked mapping example (source dict → every v1.4.0 block), and the
`--dry-run` path is how you confirm a mapping before anyone submits. Verified
dry-run output:

```
[mapping valid] schema=v1.4.0  canonical_id=evican-brightfield-batch-01  locations=1  channels=2
{ ...full JSON payload... }
[dry-run submit OK] would register -> dataset_id placeholder 00000000-0000-4000-8000-000000000000
```

## Prerequisites

```bash
uv sync --all-groups   # installs catalog_client + dev tools into .venv
```

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
| license / access / owner / PHI | `governance` | `.with_governance(license=..., access_scope=..., data_owner=..., is_phi=...)` |
| assay / instrument / sub-modality | `metadata.experiment` | `.with_experiment(sub_modality=..., assay=[OntologyEntry(...)])` |
| organism / tissue / disease | `metadata.sample` | `.with_sample(organism=[OntologyEntry(...)], tissue=[TissueEntry(...)])` |
| cell/read counts, channels, dims | `metadata.data_summary` | `.with_data_summary(cell_count=..., channels=[ChannelMetadata(...)], ...)` |
| QC results | `data_quality` | `.with_data_quality(checks_passed=..., checks_failed=...)` |
| provenance link | lineage edge | `.with_lineage(source, lineage_type=LineageType...)` |

Ontology values are `OntologyEntry(label=..., ontology_id=...)`; tissue adds
`TissueEntry(..., type=...)`. Per-channel biology is
`ChannelMetadata(..., biological_annotation=BiologicalAnnotation(...))`.

## Registering — the call the script makes

`.submit()` runs a duplicate check (GET `/api/datasets/` on the signature) then
creates (POST `/api/datasets/`), returning the new `dataset_id`. Flags:

- `submit(error_on_duplicate=False)` — return the existing id instead of raising `DuplicateDatasetError`.
- `submit(update_if_exists=True)` — PATCH the existing record. Mutually exclusive with `error_on_duplicate=True`.

Get a token from the catalog's `/docs` → Token → `/token/issue` (see
[`README.md`](../../../README.md)). Pass it via the `CATALOG_API_TOKEN` env var;
never hard-code it.

## Test

```bash
uv run pytest -q          # 207 passing
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
