---
name: registration-script
description: Procedure and judgment for producing correct catalog records from code — order of operations, installing catalog-client, the registration template and its pipeline-safety rules, fields.json (field types, required, allowed values), search patterns for duplicates and lineage parents, computing sizes and checksums, deciding governance and data-quality values, ontology terms, lineage and collections, and updating or versioning records on later runs. Use when writing, reviewing, or changing a script that registers datasets, when finding data or checking "is this already registered?", or when asked how registration from a pipeline, notebook, or cron job should work.
---

# Producing correct records from code

The deliverable is a script the user owns and runs: a copy of the template in `template/`, with
only its AGENT-EDITABLE functions and `mapping.json` changed. Field meanings are in the catalog docs
and field shapes in `fields.json` (below); this skill never restates them. Scripts are written by the `script-writer` agent
(`/catalog:register` gathers its inputs).

## Order of operations

1. **Check access**: `"${CLAUDE_PLUGIN_ROOT}/scripts/check_auth.sh"` (what
   `/catalog:whoami` runs; `catalog-guide`). Tell the user the environment it names. Writes need a
   write-capable token.
2. **Search for existing records** (search patterns, below): `catalog resolve <uri>` per data location, and
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
10. **Verify**: after a real run the script prints, for each project with at least one registered
    record, `Search page (<env>, project <project>): <CATALOG_API_URL>/search?sort=last_modified&project=<project>`.
    Always show the user that link: it opens the catalog UI (SSO login) on that project with the
    most recently modified records first, so they can see what was just registered or updated.
    Dry runs and projects whose records all failed print no link.

The script registers into whatever `CATALOG_API_URL` names (`catalog-guide`) and logs
`env=<env> url=<url>` first; state that environment before every run. Sandbox first, always:
`--dry-run`, then a real run, against a dev or staging URL; then the same two steps with the
variables pointed at prod. A plugin hook refuses a non-dry run against a prod or `unknown` URL
unless a passing `--dry-run` of the same script and config bytes against that same URL was
recorded; dev and staging runs are not blocked.

## Installing the client

The access check (`check_auth.sh`) already sets up `./.venv` with the latest released
client. To install by hand (upgrading, a repo with its own environment, no uv) or when the client's
schema version is behind, read `${CLAUDE_PLUGIN_ROOT}/skills/registration-script/reference/install.md`.

## The template

`template/register.py` plus `template/mapping.json`. Copy both next to each other.

**TEMPLATE-OWNED** (do not edit; a PostToolUse hook diffs it against the template): `--dry-run`,
`--config`, `--limit N` (first trial), `--workers` (1-16), `--payload-dir`;
`CATALOG_API_URL`/`CATALOG_API_TOKEN` lookup by name (`catalog_connection()`) and the environment
name from the URL; `RetryPolicy` (exponential backoff with jitter,
honours 429/`Retry-After`); `check_compatibility()` at startup; per-record local validation, including the shared-storage check on every asset location;
`run_batch()` with per-record isolation; the summary line (`48 registered, 2 failed: ...`); the
search-page link per registered project (step 10); exit 1
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

Use the client for every field it supports. A field marked **API-only** in `fields.json` cannot
go through `DatasetRequest`; flag it to the user rather than
writing raw HTTP, which would bypass the dry run and the upsert.

## Fields: `fields.json`

`${CLAUDE_PLUGIN_ROOT}/skills/registration-script/fields.json` is the machine-readable field list for
dataset, asset, collection and lineage records: type, required, allowed values, defaults, and
whether extra keys are kept. The validator, generated scripts and `metadata-reviewer` all read it,
so checks and explanations agree. Look a field up with
`python3 -c "import json,sys; print(json.dumps(json.load(open(sys.argv[1]))['models']['dataset']['fields']['governance.is_pii'], indent=1))" "${CLAUDE_PLUGIN_ROOT}/skills/registration-script/fields.json"`.
A field not in it does not exist: a misspelt key in a block that accepts extra keys is stored
silently, and at the top level of a record it is dropped. Meanings and examples are in the docs.

- **Client first, API second.** It is generated from the client's models, compared with the API
  spec. `source` says how to send a field: `both` through the client; `api-only` over REST until the
  client catches up; `client-only` means the API drops it.
- **Staleness.** `stamp.client_version` names the client it was built from. When the installed client
  is newer (the session-start check warns), fields added since are missing: regenerate with the
  Python that has the client installed, `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/generate_fields.py"`
  (reads the spec with `CATALOG_API_TOKEN`), or read the installed models directly
  (`DatasetRequest.model_json_schema()`) and say `fields.json` is behind.

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
| Shared storage only | Every asset location is on shared organization storage (`catalog-guide`, rules) | `location_problem()` per asset; `validate_record.py` |
| Safe to try | Dry run; dev or staging before production | `--dry-run`, environment logged from the URL, prod guard hook |

The linter (`scripts/lint_registration_script.py`, run by the PostToolUse hook and runnable by
hand) enforces the agent-side half of this table.

## Record field values

**Never invent a value**: empty is honest; a fabricated value is a data-quality bug. Governance is
always the user's answer, never yours.

Before filling any record field, read `${CLAUDE_PLUGIN_ROOT}/skills/registration-script/reference/fields.md`: computed fields (size, checksums, reusing
storage checksums, file counts) and judgment fields (governance questions, data quality evidence,
ontology terms, fields with no named slot).

## Search patterns

Every call here is a `GET`. Use the `catalog` CLI (installed with the client; table on a terminal,
JSON when piped; exit 3 = auth, 4 = not found) or, without the client, stdlib REST with the token
sent only as the `X-catalog-api-token` header. Plugin hooks auto-approve these reads.

| Question | CLI | REST (`/api/v1/…`) |
|---|---|---|
| Free text + filters, with facet counts | `catalog search --q liver --organism "Homo sapiens"` | `GET datasets/search/` |
| Stored values for a filter | `catalog facets --fields tissue` | `GET datasets/search/?facets=tissue&limit=1` |
| Exact coordinates | `catalog list --canonical-id X --version V --project P` | `GET datasets/?canonical_id=X` |
| One record | `catalog get <uuid>` | `GET datasets/{id}` (UUID, not `canonical_id`) |
| Which dataset holds this path? | `catalog resolve s3://bucket/path/` | `GET datasets/resolve?uri=…` |
| Upstream / downstream | `catalog lineage <uuid> --direction up` | `GET lineage/?destination_dataset_id=…` |

- **Duplicates before registering:** `catalog resolve <uri>` per data location is the most reliable
  check (`--scope ancestor` for a dataset on a parent folder, `--scope descendant` for anything
  underneath; a bare POSIX path needs `--storage-platform`). Then `catalog list` on the signature,
  which is the lookup `register()` itself does. There is no search by checksum; compare checksums on
  the records `resolve` returns.
- **Lineage parents:** find the parent's UUID or coordinates (`DatasetRef`) and confirm the exact
  record with the user before it goes into `mapping.json`.
- **Exact filters beat free text.** `q` is OR-tokenized (`red blood cell` matches `red OR blood OR
  cell`), so multi-word terms return false positives. Confirm a stored value with one facet request,
  then filter on it; never guess a controlled value. Zero hits for a phrase does not mean absent.
- **Pagination:** `datasets/search/` and `resolve` are cursor-only (pass `next_cursor` back as
  `cursor`; `null` = done); the list route takes a cursor or `offset` up to 10000; collections,
  lineage and history use `offset` + `limit`. Keep filters and sort identical across a walk. The SDK's
  `iter_search` / `iter_all` / `iter_resolve` manage cursors.
- `incoming_lineage`, `outgoing_lineage` and `collections` are `null` unless requested
  (`--lineage` / `--collections`); never conclude "no lineage" from a response that left them off.
- Report only ids, owners, locations and counts that came back from the API in this session.

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
- **New version** (new `version` value): a new record. Link it `version_of` the previous one.
  Reprocessed data (new processing, not a re-run of the same one) is also a new record, linked
  `transformed_from`; never mutate the parent.
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
