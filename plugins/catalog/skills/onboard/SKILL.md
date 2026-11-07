---
name: onboard
description: First-run guide to the Scientific Dataset Catalog. Finds out what the user wants (find data, register once, or automate registration), checks their setup, explains the catalog in their own terms, and gets them to one real success in a dev or staging catalog. Use when someone is new to the catalog, asks "where do I start?", accepts the onboarding offer, or runs /catalog:onboard.
---

# Onboarding

Goal: one early success, then hand off. Teach as little as possible here; the other skills hold
the detail. The first win targets a dev or staging catalog, never production. Ask one question at a time and wait for the answer.

## 1. Triage (2–3 questions, one at a time)

1. What do you want to do: **find** data, **register** a dataset once, or **automate**
   registration from a pipeline?
2. What kind of data, and which shared storage holds it (S3, which HPC site, which CoreWeave
   cluster)? If it is only on their own machine or in personal storage, it cannot be registered
   until it is copied to shared storage (`concepts`, "What can be registered"); offer the find path
   meanwhile.
3. Have you used the catalog or its Python client before?

Skip questions the user has already answered.

## 2. Readiness

Run `"${CLAUDE_PLUGIN_ROOT}/scripts/check_auth.sh"` and read it with the user, starting
with the environment it names.

- `CATALOG_API_URL` not set → `auth` skill (environments, where the token goes), then rerun.
- `environment` is `prod` or `unknown` → ask the user to point `CATALOG_API_URL` and
  `CATALOG_API_TOKEN` at a dev or staging catalog for the trial (`auth`, switching); the find path
  can continue meanwhile.
- No token or token rejected → `auth` skill (getting a token), then rerun.
- Goal needs writes and `write` is `no` → `auth` (getting write access). They can still finish the
  find path and a registration dry run meanwhile.
- The check creates `./.venv` with uv when there is no Python environment; tell the user where.
  `client version: not installed` (uv missing or the install failed) or older than 1.3.0, and the
  goal is register/automate → install steps in `registration-script`.

## 3. Primer, in their terms

Three or four sentences that map their data onto the catalog, for example: "Your 40 FASTQ files from
one run would be the assets of one dataset; the count matrix you make from them would be a second
dataset, linked to the first by lineage; a paper using both would be a collection." Use their data
type and paths. For anything deeper, or if granularity is unclear, use `concepts`; do not recite it.

## 4. Path by goal

| Goal | Next |
|---|---|
| Find | `search`: run one search for something they care about and show the result |
| Register once | `concepts` (is it one dataset?), `field-reference` (fields as they come up), then `/catalog:register` |
| Automate | As register once, then the template and pipeline-safety rules (`registration-script`) and a pipeline credential (`auth`) |

## 5. First win, in dev or staging

- **Find**: a search that returns a record they recognize, or a confirmed "not registered yet".
- **Register/automate**: `/catalog:register` for one small, real dataset that already lives on
  shared storage (`--limit 1`); dry run; review with `metadata-reviewer`; register to that dev or staging catalog; then
  open the search-page link the run prints (`registration-script`, verify) and find it there. Never use local files as a stand-in.

Governance values (`is_pii`, `is_phi`, `license`, `data_steward`) are always asked, never inferred,
even outside production.

## 6. Finish

Summarize what they did, the one next step for their goal, and where help lives: `/catalog:debug`
for failures, `/catalog:whoami` for access, `/catalog:validate` for a draft record. Then write the
marker so the onboarding offer stops:

```bash
mkdir -p "${CLAUDE_PLUGIN_DATA}" && printf '{"status":"completed","onboarding_version":1,"date":"%s"}\n' "$(date +%F)" > "${CLAUDE_PLUGIN_DATA}/onboarding.json"
```

If they stop early or decline, write `{"status":"declined"}` to the same file instead and tell them
`/catalog:onboard` restarts this any time.
