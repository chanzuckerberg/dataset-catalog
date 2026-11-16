---
name: catalog-guide
description: Getting started with the Scientific Dataset Catalog and the rules for every catalog task. Runs onboarding (find data, register once, or automate registration) and routes questions to the catalog docs — concepts (datasets, assets, lineage, collections, "is this one dataset?"), field meanings and allowed values, error messages, tokens and access, environments. Use when someone is new to the catalog, asks "where do I start?", accepts the onboarding offer, runs /catalog:onboard, asks what a catalog term or field means, pastes a catalog error, or asks how to get or check access.
---

# Catalog guide

Facts live in the catalog docs (the `catalog-docs` MCP server). This skill holds the onboarding
steps, the rules that apply everywhere, and how to use the docs. Registration procedure lives in
`registration-script`.

## Rules (everywhere)

- **Environment comes from `CATALOG_API_URL`.** Its host names the environment (`dev`, `staging`,
  `prod`); a host naming none is `unknown` and treated as production. There is no pinned default.
  Tell the user which environment and URL a check or run targets, every time. Trials, onboarding
  and first runs go to dev or staging, never production.
- **Tokens are never seen.** Never print, read, echo or ask for a token value; credentials are read by
  variable name only (`CATALOG_API_TOKEN`), exported from the user's shell init file, not Claude Code
  settings. Check access only with `"${CLAUDE_PLUGIN_ROOT}/scripts/check_auth.sh"` (what
  `/catalog:whoami` runs). A hook blocks writing a token into a file.
- **Governance values are always asked, never inferred** (`is_pii`, `is_phi`, `license`,
  `data_steward`, `data_owner`), even outside production. "Not sure" stays unanswered.
- **Register only data on shared organization storage** (an S3 bucket, a project area on an HPC site
  or CoreWeave cluster, an external public source). Never a laptop or workstation disk, external
  drive, temp directory, home directory, personal scratch, or personal bucket — samples included.
  Generated scripts and the validator reject local and personal paths; they cannot detect a personal
  bucket, so ask.
- **One question at a time**, and skip what the user already answered. Don't dump concept material;
  explain only what the next step needs, in the user's terms.

## Using the docs

Search the `catalog-docs` MCP, then answer in the user's terms and cite the page.

| Question | Where the answer comes from |
|---|---|
| What a dataset, asset, lineage edge or collection is; "is this one dataset?"; collection vs `project`; limits | Docs concept pages and decision guides |
| What a field means, examples by data type | Docs field reference |
| A field's type, whether it is required, allowed values | `registration-script` `fields.json` (built from the client; authoritative). Fields marked **API-only** need REST until the client catches up |
| An error message | Search the docs for the **exact error text** first; then read the full message (the SDK formats HTTP errors as `HTTP <status>: <detail>`) |
| Getting a token, write access, pipeline credentials, rotation | Docs auth pages |

Prefer reference pages over tutorials and guides when they disagree; the reference pages are
authoritative. If the docs and `fields.json` disagree on a field's shape, `fields.json` wins and the
docs are stale: say so.

If the MCP is unreachable (for example on an HPC node without internet), say so and give the docs
URL, https://docs.biohub.ai, rather than answering from memory.

## Onboarding

Goal: one early success, then hand off. Teach as little as possible here.

### 1. Triage (2–3 questions, one at a time)

1. What do you want to do: **find** data, **register** a dataset once, or **automate**
   registration from a pipeline?
2. What kind of data, and which shared storage holds it (S3, which HPC site, which CoreWeave
   cluster)? If it is only on their own machine or in personal storage, it cannot be registered
   until it is copied to shared storage (rules above); offer the find path meanwhile.
3. Have you used the catalog or its Python client before?

### 2. Readiness

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/check_auth.sh"` and read it with the user, starting with the
environment it names.

- `CATALOG_API_URL` not set, no token, or token rejected → docs auth pages (getting a token, where it
  goes), then rerun.
- `environment` is `prod` or `unknown` → ask the user to point `CATALOG_API_URL` and
  `CATALOG_API_TOKEN` at a dev or staging catalog for the trial; the find path can continue meanwhile.
- Goal needs writes and `write` is `no` → docs access-request steps. They can still finish the find
  path and a registration dry run meanwhile.
- The check creates `./.venv` with uv when there is no Python environment; tell the user where.
  `client version: not installed` or older than 1.3.0, and the goal is register/automate → install
  steps in `registration-script`.

### 3. Primer, in their terms

Three or four sentences that map their data onto the catalog, drawn from the docs' concept pages,
for example: "Your 40 FASTQ files from one run would be the assets of one dataset; the count matrix
you make from them would be a second dataset, linked to the first by lineage; a paper using both
would be a collection." Use their data type and paths.

### 4. Path by goal

| Goal | Next |
|---|---|
| Find | Search patterns in `registration-script`: run one search for something they care about and show the result |
| Register once | `/catalog:register` |
| Automate | As register once, then the pipeline-safety rules (`registration-script`) and a pipeline credential (docs auth pages) |

### 5. First win, in dev or staging

- **Find**: a search that returns a record they recognize, or a confirmed "not registered yet".
- **Register/automate**: `/catalog:register` for one small, real dataset that already lives on
  shared storage (`--limit 1`); dry run; review with `metadata-reviewer`; register to that dev or
  staging catalog; then open the search-page link the run prints and find it there. Never use local
  files as a stand-in.

### 6. Finish

Summarize what they did, the one next step for their goal, and where help lives: `/catalog:debug`
for failures, `/catalog:whoami` for access, `/catalog:validate` for a draft record, the docs for
everything else. Then write the marker so the onboarding offer stops:

```bash
mkdir -p "${CLAUDE_PLUGIN_DATA}" && printf '{"status":"completed","onboarding_version":1,"date":"%s"}\n' "$(date +%F)" > "${CLAUDE_PLUGIN_DATA}/onboarding.json"
```

If they stop early or decline, write `{"status":"declined"}` to the same file instead and tell them
`/catalog:onboard` restarts this any time.
