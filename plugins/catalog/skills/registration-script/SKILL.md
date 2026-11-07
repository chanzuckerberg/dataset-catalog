---
name: registration-script
description: Procedure and judgment for producing correct catalog records from code — order of operations, installing catalog-client, the registration template and its pipeline-safety rules, computing sizes and checksums, deciding governance and data-quality values, ontology terms, lineage and collections, and updating or versioning records on later runs. Use when writing, reviewing, or changing a script that registers datasets, or when asked how registration from a pipeline, notebook, or cron job should work.
---

# Producing correct records from code

The deliverable is a script the user owns and runs: a copy of the template in `template/`, with
only its AGENT-EDITABLE functions and `mapping.json` changed. Field definitions are in
`field-reference`; this skill never restates them. Scripts are written by the `script-writer` agent
(`/catalog:register` gathers its inputs).

## Order of operations

1. **Check access**: `"${CLAUDE_PLUGIN_ROOT}/scripts/check_auth.sh"` (what
   `/catalog:whoami` runs; auth skill). Tell the user the environment it names. Writes need a
   write-capable token.
2. **Search for existing records** (search skill): `catalog resolve <uri>` per data location, and
   parents for lineage. An existing record means this run is an update.
3. **Build** each record: the AGENT-EDITABLE functions.
4. **Validate locally**: the template calls `to_dataset_request()` per record before any API call;
   for a standalone payload use `/catalog:validate`.
5. **Dry run**: `--dry-run` calls `client.plan()`, which is read-only and reports `create`,
   `update`, or `skip` plus the lineage edges it would add. It writes each payload to
   `catalog-dry-run/` for review (`metadata-reviewer` agent).
6. **Create or update**: `client.register(request, update_if_exists=True, error_on_duplicate=False)`,
   an idempotent upsert that also skips lineage edges that already exist.
7. **Assets** go in with the dataset (its `locations`); there is no separate attach step.
8. **Lineage** edges are created by `register()` from the request's `lineage` list.
9. **Collections**: `client.collections.add_dataset(collection_id, dataset_id)` after the dataset exists.
10. **Verify**: find the new record with search, as the user would.

The script registers into whatever `CATALOG_API_URL` names (auth skill) and logs
`env=<env> url=<url>` first; state that environment before every run. Sandbox first, always:
`--dry-run`, then a real run, against a dev or staging URL; then the same two steps with the
variables pointed at prod. A plugin hook refuses a non-dry run against a prod or `unknown` URL
unless a passing `--dry-run` of the same script and config bytes against that same URL was
recorded; dev and staging runs are not blocked.

## Installing the client

Python 3.11+, never the system interpreter. The access check (`check_auth.sh`, auth skill) already
sets this up: it reuses an active virtual environment or `./.venv`, and otherwise creates `./.venv`
with uv and installs the latest released client. Install by hand only to upgrade, to use a repo
that manages its own environment (in this monorepo, `uv sync --all-groups`), or where uv is
unavailable. Install a released tag, never `main`:

```bash
TAG=$(gh release list --repo chanzuckerberg/dataset-catalog --json tagName,publishedAt \
  --jq 'map(select(.tagName | startswith("catalog-client-v"))) | sort_by(.publishedAt) | reverse | .[0].tagName')
python -m venv .venv && source .venv/bin/activate
pip install "git+https://github.com/chanzuckerberg/dataset-catalog.git@${TAG}#subdirectory=dataset-catalog-client"
```

This installs the `catalog_client` package and the `catalog` CLI. Generated scripts need
`catalog-client>=1.3.0,<2`; the PEP 723 header records that, but because the client is installed from
git rather than a package index, install it as above rather than relying on `uv run` to resolve it.
If the installed client's `record_schema_version` is behind the `Current` row in the repo's
`schema/README.md`, re-run the install with `--upgrade`; if the newest release is still behind, the
release has not shipped yet: register against the installed version and tell the user.

## The template

`template/register.py` plus `template/mapping.json`. Copy both next to each other.

**TEMPLATE-OWNED** (do not edit; a PostToolUse hook diffs it against the template): `--dry-run`,
`--config`, `--limit N` (first trial), `--workers` (1-16), `--payload-dir`;
`CATALOG_API_URL`/`CATALOG_API_TOKEN` lookup by name (`catalog_connection()`) and the environment
name from the URL; `RetryPolicy` (exponential backoff with jitter,
honours 429/`Retry-After`); `check_compatibility()` at startup; per-record local validation, including the shared-storage check on every asset location;
`run_batch()` with per-record isolation; the summary line (`48 registered, 2 failed: ...`); exit 1
if any record failed, 2 on configuration or compatibility errors.

**AGENT-EDITABLE** (between the `AGENT-EDITABLE` and `END AGENT-EDITABLE` markers):

| Function | Returns | Notes |
|---|---|---|
| `discover_records(config)` | iterator of `Source(key, attrs)` | Yield lazily. `key` must be stable: it names the record in logs and the summary |
| `build_dataset(src, config)` | `RegistrationBuilder` | Signature, modality, type, governance, metadata blocks |
| `build_assets(src, config)` | `list[DataAssetRequest]` | Streaming size and checksum (below) |
| `lineage_parents(src, config)` | `list[LineageSpec]` | `source_ref=DatasetRef(canonical_id, version, project)` or `source_dataset_id` |
| `collections_for(src, config)` | `list[str]` | Collection ids that already exist |

Agent code may add imports at the top of its region. Every data-specific value (paths, globs,
governance answers, collection ids) goes in `mapping.json`; `null` there means "not answered yet"
and fails validation, which is intended.

Use the client for every field it supports. A field marked **API-only** in `field-reference` cannot
go through `DatasetRequest`; flag it to the user rather than
writing raw HTTP, which would bypass the dry run and the upsert.

## Pipeline-safety rules

| Category | Rule | Where it holds |
|---|---|---|
| Re-runs | Look up first; update or create; never duplicate | `register(..., update_if_exists=True, error_on_duplicate=False)`; stable signatures |
| Isolation | One failing record never stops the batch | `run_batch`; agent code raises, never exits |
| Visibility | Log each failure; summary at the end; non-zero exit if any failed | `run_batch` logs `<key> failed: <ExcType>: <msg>`; `report.summary()`; `report.exit_code` |
| Good client | Backoff with jitter, honour 429/`Retry-After`, cap concurrency | `RetryPolicy`; `--workers` capped at 16 |
| Env drift | Pin the client; check compatibility at startup | PEP 723 pin; `check_compatibility()` |
| Memory | Stream records and bytes; never load everything | `discover_records` yields; checksums stream |
| No interactive steps | Credentials from the environment or a secrets manager; no prompts | `catalog_connection()`; linter rejects `input()` |
| Fail fast | Validate locally before any API call | `to_dataset_request()` per record |
| Shared storage only | Every asset location is on shared organization storage (`concepts`, "What can be registered") | `location_problem()` per asset; `validate_record.py` |
| Safe to try | Dry run; dev or staging before production | `--dry-run`, environment logged from the URL, prod guard hook |

The linter (`scripts/lint_registration_script.py`, run by the PostToolUse hook and runnable by
hand) enforces the agent-side half of this table.

## Computed fields

- **Size.** `size_bytes` is the asset's total bytes: the file size, or the sum over every file in a
  folder. Take it from storage metadata (`ChecksumResult.total_size`), not by reading the bytes.
  Unknown is unset, never `0`.
- **Checksums.** Prefer the client: `catalog checksum <path|s3://...>` from a shell, or
  `catalog_client.utils.checksum.compute_checksum(path, algorithm=...)` in code. Both stream in
  chunks and never load a file whole. Record the algorithm with the digest (`result.content_digest`,
  `result.algorithm.value`). Algorithm: `blake3` when the `checksum` extra is installed (fastest for
  very large files, and the default then), else `blake2b` (stdlib); on S3, `crc64nvme`/`crc32` let
  you reuse what S3 already stores instead of downloading.
- **Reusing storage checksums.** Check how a stored value was made before reusing it. A multipart S3
  ETag (`"…-N"`) is not an MD5 and not comparable across uploads; S3 composite (multipart) checksums
  depend on part size. The client's S3 path reuses only full-object checksums and ignores the rest.
- **File counts.** `file_count` for folders: count while walking (`os.walk`), not by listing into memory.

## Judgment fields

**Never invent a value.** Empty is honest; a fabricated value is a data-quality bug. If the source
lacks something optional (checksum, owner), leave it unset.

**Governance: ask a human; default to asking.** Allowed values and meanings are in `field-reference`.

1. Does the user know the consent terms, data-use agreement, or source license for this data?
   No → stop and ask who does (the data owner or steward). Do not register.
2. Is the data derived from human participants (donor tissue, clinical samples, genotypes,
   identifiable images)? Yes → `is_pii`/`is_phi` come from the consent and the steward, in writing
   from the user. No (commercial cell lines, model organisms, synthetic data) → still have the user
   confirm both flags; never set them for the user.
3. `license` only as the user states it. `data_steward` is a named person or team the user gives.
4. Record each answer in `mapping.json`. Values that are unknown stay `null` so the record fails
   validation instead of shipping a guess.

**Data quality.** Each entry in `checks_passed` / `checks_failed` / `checks_skipped` needs evidence
the user can point to (a QC report, a metrics file, a pipeline step). Put the evidence files in
`report_assets` / `metrics_assets`. No evidence, no entry.

**Ontology terms.** An `ontology_id` is set only when an ontology lookup returns a term whose label
or synonym matches the source label exactly (case-insensitive), e.g. via the EBI OLS4 search API
(`https://www.ebi.ac.uk/ols4/api/search?q=<label>&ontology=<ncbitaxon|uberon|efo|cl|...>`). On no
confident match, or a failed lookup (retry a 429/5xx/timeout once), keep the label, leave
`ontology_id` unset, and list the gap for the user. A field may be filled from another column only
when that value formally determines it (a cell line's ontology ancestors pin its species); if it
could map to several values, leave it unset. Show the user the derivation rule and the rows it
leaves unset, and get approval before coding it.

**Fields with no named slot.** Keep them rather than dropping them: sample attributes as extra
keys on `with_sample(...)` (ontology concepts as `[OntologyEntry(...)]`, not bare strings),
measurements on `with_data_summary(...)`, experiment details on `with_experiment(...)`, and anything
else under the single `additional_metadata` key via `with_custom_metadata(additional_metadata={...})`;
governance is the exception (see its `field-reference` entry). Use custom metadata only when no proper
field exists.

## Lineage and collections

Both ends of an edge must exist first: register parents before children (order `discover_records`
accordingly, or run the parent script first). `DatasetRef` parents are resolved by the client; an
unresolvable parent fails that record with `LineageResolutionError`, not the batch. Collections must
exist before records are added; create one with `client.collections.create(CollectionRequest(...))`
once, outside the per-record loop, and put its id in `mapping.json`. Adding a dataset that is
already a member is a no-op `PUT`.

## Lifecycle

- **After the first run, most runs are updates.** The upsert matches on the signature. An update
  writes exactly what you send: omitted fields are not backfilled, and omitted locations are
  tombstoned, so always build the record's complete state.
- **New version** (new `version` value): a new record. Link it `version_of` the previous one; see
  `concepts` for when reprocessing is a new record instead.
- **Deprecate**: leave superseded versions in place, linked by lineage. Tombstone
  (`client.datasets.delete(id)`) only a record that should never have existed, and only with the user.

## Builder gotchas

- `with_experiment` / `with_sample` / `with_data_summary` each **replace** their whole block.
  Build each block in one call (e.g. the full `channels=[...]` list at once).
- Blocks that accept extra keys keep a typo'd field name as an extra. Read the dry-run payload once;
  a value at an unexpected nesting level is a typo.
- `record_schema_version` is set by the model; do not map onto it.
- Identity comes from the signature, so derive `canonical_id` / `version` / `project` from stable
  source ids, the same way every run.
