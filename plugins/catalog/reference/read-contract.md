# Read-only operating contract

Shared policy for the read-only Catalog skills (`catalog-read`, `catalog-search`).
Each skill loads this first, then applies its own ceilings, tool selection, and
decision rules. `reference/rest.md` remains authoritative for endpoints, filters,
pagination, facet behavior, the dataset record shape, and OLS expansion mechanics.

## Read-only prohibitions

* **Never** issue a `POST`, `PUT`, `PATCH`, or `DELETE` to the Catalog. Every
  Catalog and OLS call is a `GET`. Registration and writes go through the
  `catalog-register` skill, never here.
* **Never** place the API token in a URL, command argument, log, or output. It
  travels only as the `X-catalog-api-token` request header.
* "Read-only" governs the **Catalog**, not the local filesystem — writing a local
  file (e.g. a chart artifact or a reduction script) is permitted.

## Configuration and credentials

Read from the environment (same contract as the CLI, SDK, and scripts):

```text
CATALOG_API_URL    base URL; defaults to production when unset
CATALOG_API_TOKEN  API token; required — sent only as the X-catalog-api-token header
```

## Validate prerequisites

Run once, before any query:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/preflight.py"
```

Exit `0` means ready. Exit `2` prints what to fix; `--no-ping` skips only the
network check. Preflight is read-only and auto-approved by the plugin hook.

If the token is missing or rejected, **stop** and tell the user to issue one at
`<base_url>/tokens` (SSO-gated, logged-in browser) and store it in their Claude
Code env settings. Do not ask for it in chat and never place it in a command.

## Detect silent failures

Never guess a controlled value (enum, facet value, or id) and filter on it.
Confirm it from `reference/rest.md` or with **one** facet-discovery request first.
Resolve a `canonical_id` to a UUID through the list route before fetching a full
record: `GET /api/datasets/?canonical_id=<value>`.

The list route may ignore an unsupported parameter and appear to match
everything. If a filter should reduce `total` but does not, report that the filter
may have been ignored rather than trusting the count.

## Output hygiene

* Lead a search or list with the **number of matches** and the exact filters or
  terms used.
* One compact row per dataset: `id`, `canonical_id`, `version`, and only the other
  fields the request asked for. Always include `id` so a follow-up record lookup
  is possible.
* Keep out of the conversation: raw JSON, command output, full record dumps, facet
  dumps, raw OLS payloads, pagination responses, and unrequested metadata. If the
  user explicitly asks for a full record, return that record and nothing else.

## Completeness labeling

Label every result — **complete**, **partial**, **truncated**, **unverified**, or
**failed** — in one line. When execution stopped at a page, row, term, or
tool-call ceiling, name the exact limit reached. Never let a partial or truncated
result read as complete or exact.

## Common stopping conditions

Stop without executing, and report the reason, when:

* `CATALOG_API_TOKEN` is missing or rejected → authentication must be configured.
* the request implies a write → out of scope; direct the user to `catalog-register`.
* a controlled value cannot be validated → report it; do not iterate guesses.
* `reference/rest.md` is needed but unreadable → report it rather than improvising.
