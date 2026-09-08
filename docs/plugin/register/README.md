# Registering datasets from Claude Code (`catalog-register`)

The `catalog-register` skill takes metadata you already have — a CSV row, a LIMS export, a JSON
blob, a spreadsheet — maps it onto the current catalog schema, and writes a **runnable registration
script** you keep. You describe your data in a Claude Code session; the mapping code, the schema
lookup and the ontology ids come back as a file you can read, re-run and commit.

It is the **only write path** in the `catalog` plugin. Everything read-only — lookups, project
listings, lineage, facet discovery, ontology-expanded search — goes through the `catalog-read` and
`catalog-search` skills, which share a `GET`-only operating contract
([`plugins/catalog/reference/read-contract.md`](../../../plugins/catalog/reference/read-contract.md)).

This page is the human-facing guide. The skill's own instructions live in
[`plugins/catalog/skills/catalog-register/SKILL.md`](../../../plugins/catalog/skills/catalog-register/SKILL.md);
you do not need to read them to use it.

**When it fires.** Ask for any of: "map this metadata onto the catalog schema", "ingest this export
into the catalog", "fit this to the dataset schema", "fill in the experiment / sample /
data_summary fields", "write me a script to register this dataset".

---

## Prerequisites

### 1. Token and URL, in your Claude Code environment settings

```text
CATALOG_API_TOKEN   required — issue one at <base_url>/tokens in a logged-in browser (SSO-gated)
CATALOG_API_URL     optional — base URL; defaults to production when unset
```

The token is read from the environment and is never typed into chat or passed on a command line.
Write permission is decided by your Okta group membership **at the moment the token is issued** and
baked in, so a read-only token stays read-only even after you join the group — reissue it.

### 2. Python 3.11+ with `catalog_client` installed

The skill's script imports `catalog_client`; the plugin does not bundle it. Install **a tagged
release, never `main`** — `main` is unreleased and may not match any published schema version. Full
detail in [`plugins/catalog/reference/install.md`](../../../plugins/catalog/reference/install.md):

```bash
# resolve the latest released tag (requires the gh CLI):
TAG=$(gh release list --repo chanzuckerberg/dataset-catalog \
  --json tagName,publishedAt \
  --jq 'map(select(.tagName | startswith("catalog-client-v"))) | sort_by(.publishedAt) | reverse | .[0].tagName')
echo "latest release: $TAG"   # e.g. catalog-client-v0.7.0

# standalone — create and activate a venv FIRST, then install that exact tag:
python -m venv .venv            # or: uv venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install "git+https://github.com/chanzuckerberg/dataset-catalog.git@${TAG}#subdirectory=dataset-catalog-client"
```

In this monorepo, `uv sync --all-groups` handles it — then run via `uv run python ...`.

The skill will ask before installing anything and will not install into a system interpreter
silently.

### 3. The plugin itself

```text
/plugin marketplace add chanzuckerberg/dataset-catalog
/plugin install catalog@dataset-catalog
/reload-plugins        # only needed if you were already in a session
```

Terminal equivalents, the update flow and the full component list are in the
[root README](../../../README.md#claude-code-plugin).

---

## The loop

The skill drives [`register_dataset.py`](../../../plugins/catalog/skills/catalog-register/scripts/register_dataset.py),
which is both the template you end up with and the harness it iterates in. It takes no `--help`;
three modes, and the default is the safe one:

| Command | What it does |
| --- | --- |
| `--fields` | Prints the **live** schema field tree, read off the installed Pydantic models. `*` marks required, `[extra=allow]` marks blocks that accept extra keys. Never stale. |
| *(no flag)* / `--dry-run` | Validates the mapping with the same Pydantic rules the API enforces, prints the payload, runs the whole submit path against an in-process fake catalog, and reports coverage. No token, no network. |
| `--submit` | Registers for real. Needs `CATALOG_API_URL` and `CATALOG_API_TOKEN`; exits 2 without them. |

What happens in order:

1. **The schema gets resolved, twice over.** The `schema/` folder on GitHub says which version is
   *current* and what each field *means*; `--fields` says what actually validates. If the installed
   client's `record_schema_version` default disagrees with the current row, the client is stale and
   gets upgraded before any mapping — the installed client always wins on conflict.
2. **The mapping gets written.** Only two functions change: `load_source()` points at your data,
   `build_request()` maps one source field per builder call. Everything else in the file is harness.
3. **Dry-run, and iterate until coverage is clean.** This is the step that catches mistakes:

   ```text
   [mapping valid] schema=v1.4.0  canonical_id=evican-brightfield-batch-01  locations=1
   [coverage] 24 mapped + 1 dropped of 25 source fields
     ✓ every source field is mapped or explicitly dropped
     metadata blocks populated: experiment, sample
   ```

   A field that is neither mapped nor explicitly dropped is reported as **SILENTLY LOST**, by name.
   That is the point of the report: every field becomes a deliberate decision — mapped, kept as an
   extra, or `src.drop(...)`-ed. Losing one by accident is not possible without being told.
4. **Preflight, then submit.** The shared preflight is read-only, auto-approved by the plugin's
   hook, and confirms the token actually works — so a 401 lands before a full mapping, not halfway
   through a write:

   ```bash
   export CATALOG_API_URL=https://your-catalog.example.com CATALOG_API_TOKEN=...
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/preflight.py"   # 0 = ready, 2 = fix config/token
   python register_dataset.py --submit
   ```

`.submit()` runs a duplicate check (`GET /api/datasets/` on the signature) and then creates
(`POST /api/datasets/`), returning the new `dataset_id`.

---

## A worked session

> **You:** I have a LIMS export at `~/exports/batch42.csv`, one row per plate. Map it onto the
> catalog schema and register it to staging.

What comes back, in order:

- The current schema version, and a note if your installed client is behind it.
- A **field-by-field mapping proposal** — each source column, the schema slot it lands in, and the
  builder call that puts it there. Columns with no named slot are called out, not dropped.
- Questions on anything it will not guess (below).
- A dry-run: the JSON payload plus the coverage report. Read the payload once — a value at an
  unexpected nesting level is the signature of a typo'd field name.
- The script itself, and a `--submit` invocation once you approve.

Ontology labels are resolved through the plugin's `ols` MCP server (EBI OLS4), so `Homo sapiens`
becomes `NCBITaxon:9606`. A label that does not resolve keeps the label and leaves `ontology_id`
unset — a CURIE is never fabricated, and unresolved labels are listed for you to fill in by hand.

Fields with no named slot are not thrown away either. Most metadata blocks are `extra="allow"`, so
sample-ish fields ride along on `.with_sample(...)`, measurements on `.with_data_summary(...)`,
experiment detail on `.with_experiment(...)`, and anything genuinely homeless lands under the single
`additional_metadata` key. `governance` is the exception: it is fixed-shape, and access/licence/
compliance fields that do not match a named governance field go to custom metadata instead.

---

## What it will stop and ask you

Being asked is not the skill being unhelpful — each of these is a value that is wrong more often
than it is right when inferred, and wrong here means a data-quality bug in a shared catalog.

| It asks about | Why it will not guess |
| --- | --- |
| `license` | Not derivable from the data. Only a value you confirm gets written. |
| `is_pii` / `is_phi` | Both default to unknown. `False` is a claim, not a default. |
| `storage_platform` | A `/hpc/...` path does not identify which of `sf_hpc` / `chi_hpc` / `ny_hpc`; an `https://` URI is not necessarily `external`. |
| `.zarr` granularity | One record per screen, plate, well or FOV is your modelling decision, and it also decides what each `location` points at. |
| Derived `organism` / `tissue` / `disease` | Only filled when *formally entailed* via the OLS hierarchy (e.g. a cell line pinning its species), never by intuition — and the rule is shown to you before it is coded. |
| Duplicate handling | See the table below; the default raises. |
| A virtual environment | Before any install, if one is not already active. |

Two values it does *not* ask about: `access_scope` is always `internal`, and
`record_schema_version` is set by the model.

---

## Re-running: duplicate handling

Identity is the signature — `canonical_id` + `version` + `project`, plus each asset's
`location_uri` / `asset_type` / `size_bytes` / `checksum` / `checksum_alg`. Pick those from stable
source ids so a re-run updates instead of duplicating. Changing one tombstones the old record and
mints a new UUID; that is intended, and it is how history is preserved.

| Call | Behaviour |
| --- | --- |
| `submit()` | **Error** — raises `DuplicateDatasetError`. The default; use it when each run should be a new record. |
| `submit(error_on_duplicate=False)` | **Skip** — returns the existing id, writes nothing. |
| `submit(error_on_duplicate=False, update_if_exists=True)` | **Update** — PATCHes the existing record in place. |

Only one may be `True`; both raises `ValueError`. Note that an update writes exactly what you send —
omitted fields are not backfilled, and omitted locations are tombstoned. Always send complete state.

---

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `KeyError` / `None` in `build_request` | Source data is missing a field the mapping assumes. Use `src.get("x")` for optional fields. |
| `ValidationError: ... Field required` on `--dry-run` | A required block was not mapped: `governance`, `metadata`, or at least one `location`. |
| `ValueError: 'x' is not a valid DatasetModality` | Map the source value onto a real enum member: `imaging`, `sequencing`, `mass spec`, `unknown`. |
| A value landed at the wrong nesting level in the payload | A typo'd field name, silently kept as an extra because the block is `extra="allow"`. Cross-check against `--fields`. |
| A block you filled in twice is missing half its content | `with_experiment` / `with_sample` / `with_data_summary` **replace** their block. Build each in a single call. |
| `DuplicateDatasetError` on `--submit` | A record with the same signature exists. Choose skip or update from the table above. |
| `ValueError: update_if_exists and error_on_duplicate cannot both be True` | `update_if_exists=True` requires `error_on_duplicate=False`. |
| `AuthenticationError` (401) | Bad or expired token — reissue at `<base_url>/tokens`. If it says *token owner does not have write permissions*, the token was issued before you had write access; reissue it. |
| `preflight` exits 2 | `CATALOG_API_TOKEN` unset, or the catalog rejected it. Guidance is on stderr. |

---

## See also

- [Claude Code plugin](../../../README.md#claude-code-plugin) — install, update, and the full
  component list (three skills, the `catalog-reader` subagent, the `ols` MCP server, the read hook)
- [`plugins/catalog/reference/read-contract.md`](../../../plugins/catalog/reference/read-contract.md) —
  the `GET`-only contract the read skills share
- [`schema/README.md`](../../../schema/README.md) — which schema version is current, and what each
  field means
- [`dataset-catalog-client/USAGE.md`](../../../dataset-catalog-client/USAGE.md) — the Python SDK, for
  writing registration code without the skill
- [`plugins/catalog/reference/install.md`](../../../plugins/catalog/reference/install.md) — client
  install detail
