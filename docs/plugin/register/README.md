# Registering datasets from Claude Code (`/catalog:register`)

`/catalog:register` turns a conversation about your data into a **registration script you own**:
a copy of the plugin's template plus a `mapping.json` with your answers, dry-run against a dev or
staging catalog before you see it. You run the script yourself, by hand or from your pipeline. Claude never
registers data on its own.

This page is the human-facing guide. The instructions Claude follows live in the plugin's skills
([`registration-script`](../../../plugins/catalog/skills/registration-script/SKILL.md),
[`catalog-guide`](../../../plugins/catalog/skills/catalog-guide/SKILL.md)) and the
[catalog docs](https://docs.biohub.ai); you do not need to read the skills.

## Before you start

- The plugin installed ([root README](../../../README.md#claude-code-plugin)).
- `CATALOG_API_URL` and `CATALOG_API_TOKEN` exported for a dev or staging catalog, from your shell
  init file rather than Claude Code settings (see the [catalog docs](https://docs.biohub.ai) auth pages).
  The script and the plugin use whatever catalog that pair names; there is no default. `/catalog:whoami`
  shows the environment and whether the token can write; write permission is
  fixed when a token is issued, so reissue it after you are granted write access.
- `catalog-client` 1.3.0+ installed from a release tag, in a virtual environment. Claude asks
  before installing anything.

## What happens

1. **Questions, one at a time.** Where the data is and what it is; what one dataset should be
   (Claude proposes, you confirm); governance (`is_pii`, `is_phi`, license, data steward, owner);
   collections and lineage parents (Claude searches, you confirm); where the script will run; and
   where to write it.
2. **A one-screen summary** to confirm, including your token status.
3. **The `script-writer` agent** copies the template, fills in only the data-specific functions and
   `mapping.json`, lints the script, and dry-runs it against your dev or staging catalog: `--limit 1` first, then
   everything.
4. **The `metadata-reviewer` agent** checks one dry-run payload for problems a validator can't see
   (granularity, implausible values, guessed governance, duplicates).
5. **You run it**: a real run against dev or staging, then, with `CATALOG_API_URL` and
   `CATALOG_API_TOKEN` pointed at prod (a production credential, usually from your pipeline),
   `--dry-run` and then the real run.

## What it will not guess

| Value | Why |
| --- | --- |
| `is_pii`, `is_phi`, `license`, `data_steward` | Decided by consent and data source. Unanswered values stay `null` and the record fails validation instead of shipping a guess. |
| Storage platform for `/hpc/...` or `https://` paths | Three HPC sites mount the same paths; internal platforms sit behind URLs. |
| What one dataset is | Your modelling decision (e.g. screen, plate, well, or field of view for an OME-Zarr store). |
| Ontology ids | Set only on an exact label match from an ontology lookup; otherwise the label is kept and the gap is listed for you. |

## The script

```bash
python register.py --dry-run    # validate locally, plan, write payloads; no writes
python register.py              # register
```

Both target whatever `CATALOG_API_URL` and `CATALOG_API_TOKEN` name, and the first log line says
which environment that is (`env=staging url=…`). To target another catalog for one command, prefix
it, keeping the token value off the command line:

```bash
CATALOG_API_URL=https://datacatalog.prod-sci-data.prod.czi.team \
CATALOG_API_TOKEN="$(cat ~/.config/catalog/prod-token)" python register.py --dry-run
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--dry-run` | off | Read-only plan (`create` / `update` / `skip` per record); payloads go to `--payload-dir` |
| `--config` | `mapping.json` beside the script | Data-specific values |
| `--limit N` | all | Process the first N records only |
| `--workers N` | 4 | Concurrent records, 1–16 |
| `--payload-dir` | `catalog-dry-run/` | Where `--dry-run` writes each payload |

It ends with a summary such as `48 registered, 2 failed: ...`; after a real run it also prints a
link per registered project to the catalog UI, `<CATALOG_API_URL>/search?sort=last_modified&project=<project>`,
with the most recently modified records first. It exits 0 when every record
succeeded, 1 when any failed (the others still went through), and 2 on configuration, credential, or
client/API compatibility errors. Re-running is safe: existing records are updated, not duplicated.
An update writes the record's complete current state, so files dropped from the source drop off the
record too.

Only the functions between the `AGENT-EDITABLE` markers and `mapping.json` are yours to change. The
rest is shared code (credentials, retries, the compatibility check, batching, the summary); the
plugin flags edits to it, and asking Claude for a change routes it through `script-writer`.

## Safety nets

- When Claude runs the script against a prod URL, or one whose host names no environment, without
  `--dry-run`, a hook refuses unless a `--dry-run` of the same script and `mapping.json` against that
  same URL passed in this Claude Code install; editing either file after the dry run requires a new
  one. Dev and staging runs are not blocked.
- A hook refuses to write a literal API token into any file.
- Keep production credentials out of Claude Code entirely: see the
  [root README](../../../README.md#keep-production-credentials-out-of-claude-code).

When something fails, `/catalog:debug` with the error text gets a diagnosis and a proposed fix.

## See also

- [`schema/README.md`](../../../schema/README.md): which schema version is current and what each field means
- [`dataset-catalog-client/USAGE.md`](../../../dataset-catalog-client/USAGE.md): the Python SDK
