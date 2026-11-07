---
name: common-errors
description: Maps exact catalog error text — API responses, catalog-client exceptions, `catalog` CLI messages, generated registration script output, validator lines, and plugin hook blocks — to cause, fix, and the skill that explains it. Use when a catalog command, registration script, or SDK call fails, or when the user pastes an error.
model: sonnet
---

# Common errors

Match on the quoted text (it is the exact string, or its stable prefix). `<…>` is a variable part.
Not listed? Read the full message: the SDK formats HTTP errors as `HTTP <status>: <detail>`, and the
detail is usually specific.

## Access

| Error text | Cause | Fix | See |
|---|---|---|---|
| `Missing required header: X-catalog-api-token` (401) | Request sent without the token header | Send `X-catalog-api-token: <token>`; not `Authorization: Bearer` | auth |
| `Invalid or expired token` (401) | Token expired, revoked, mistyped, or for another environment | Issue a new token for this environment; check the variable with `/catalog:whoami` | auth |
| `does not have write permissions` | Token issued before write access was granted | Issue a new token after access is granted | auth |
| An HTML page (`<!DOCTYPE html>`) instead of JSON | Request missed the header or hit a non-`/api/` path, so the SSO proxy answered | Use `/api/v1/...` paths with the header | search |
| `set CATALOG_API_URL and CATALOG_API_TOKEN for the catalog to register into` (script exit 2; names only the missing one when one is set) | The generated script has no catalog to target; there is no default | Export the pair for a dev or staging catalog first | auth |
| `check_auth: CATALOG_API_URL is not set, so there is no catalog to check.` (whoami, exit 2) | No catalog URL in the environment | Export `CATALOG_API_URL` and `CATALOG_API_TOKEN`, then rerun | auth |
| `none — set CATALOG_API_TOKEN for this catalog` (whoami `token source`, exit 2) | URL set, token not | Export the token for that catalog | auth |
| `unknown — CATALOG_API_URL names no dev/staging/prod host; treated as production` (whoami `environment`) | The URL's host names no environment | Not an error; production rules apply. Check the URL is the catalog you meant | auth |
| `check_auth: could not reach <url> (<environment>): <reason>. Check network/VPN.` (whoami, exit 1) | Network, VPN, or a wrong URL | Check VPN and the URL | auth |
| `error: set CATALOG_API_URL and CATALOG_API_TOKEN in the environment.` (CLI exit 2) | The CLI reads only the generic pair | Export both | auth |
| `authentication failed — check CATALOG_API_TOKEN: HTTP 401: …` (CLI exit 3) | As the 401 rows above | As above | auth |
| `write: unknown — needs /api/v1/token/validate` (whoami) | Deployment predates the token-validate route | Not an error; write is unconfirmed | auth |

## Validation (local or 422)

| Error text | Cause | Fix | See |
|---|---|---|---|
| `<path>: Field required` | A required field or block is missing (`governance`, `metadata`, `locations`, `governance.data_steward`, …) | Supply it; for governance, ask the user | field-reference |
| `governance.is_pii: Input should be a valid boolean` (also `is_phi`) | `null` in `mapping.json`: not yet answered | Get the answer from the user; never default to `false` | registration-script |
| `<path>: Input should be '<a>', '<b>' or '<c>'` | Value outside the allowed set | Map the source value onto an allowed one | field-reference |
| `'<x>' is not a valid DatasetModality` (or `StoragePlatform`, `DatasetType`, …) | Enum built from an unmapped or `null` source value | Map it explicitly; for `None is not a valid StoragePlatform`, fill `assets.storage_platform` in `mapping.json` | field-reference |
| `<uri> cannot be registered: <reason>` (script) / `locations.<n>.location_uri: not registrable, <reason>` (validator) | Asset points at a local disk, temp dir, home directory, or a bare path on a non-cluster platform | Register the copy on shared storage; never a local stand-in | concepts |
| `locations: List should have at least 1 item after validation, not 0` | No assets built | Fix `build_assets` | registration-script |
| `<path>: Extra inputs are not permitted (not in the schema; the API would drop it)` | Misspelt or unknown key (from `validate_record.py`; pydantic would silently drop it) | Use the real field name | field-reference |
| `<root>: Input should be a valid dictionary` | Payload is not a JSON object | Validate one record object per file | — |
| `Unknown facet field(s): [<x>]. Allowed: [<…>].` (422) | Facet name not supported | Use one from the list in the message | search |
| `Input should be greater than or equal to 1` on `limit` (422) | `limit=0` | Use a limit within the route's range | search |
| `limit must be <= <n> on <route>, got <m>` / `limit must be >= 1` | SDK refused an out-of-range page size before sending | Same | search |

## Records and lineage

| Error text | Cause | Fix | See |
|---|---|---|---|
| `Dataset already exists: DatasetRef<…>. Use update_if_exists=True to update or error_on_duplicate=False to skip.` | `register()` / `submit()` called with defaults on a re-run | Call `register(request, update_if_exists=True, error_on_duplicate=False)` (the template does) | registration-script |
| `update_if_exists and error_on_duplicate cannot both be True` | Both flags set | `update_if_exists=True` needs `error_on_duplicate=False` | registration-script |
| `Multiple datasets found (<n>) for DatasetRef<…>` | Several live records share one signature | Stop; list them (`catalog list …`) and have the owner resolve it | search |
| `Could not resolve DatasetRef(canonical_id=…, version=…, project=…): …` | Lineage parent not registered (or wrong coordinates) | Register the parent first, or fix the reference | concepts |
| `Dataset '<id>' not found` (404) | Wrong or tombstoned id, or a `canonical_id` passed where a UUID is needed | Look the record up again; resolve coordinates through the list route | search |
| `Dataset 'resolve' not found` | The deployment predates `datasets/resolve` (the path fell through to the by-id route) | Use `catalog list` by coordinates; not evidence the URI is unregistered | search |
| `Pass either \`cursor\` or \`offset\`, not both.` (400) | Both paging styles sent | Use one | search |
| HTTP 409 creating a lineage edge | The API refused the edge as conflicting with an existing one | List edges for the pair; do not retry blindly | concepts |
| HTTP 503 from search | Search backend unavailable | Retry once later, then report; never substitute guesses | search |

## Generated scripts and hooks

| Error text | Cause | Fix | See |
|---|---|---|---|
| `<key> failed: <ExcType>: <msg>` | One record failed; the batch continued | Look up `<msg>` in this skill; fix and re-run (re-runs are idempotent) | registration-script |
| `<n> registered, <m> failed: …` with exit 1 | Summary after a batch with failures | Fix the failed records; re-run the whole script | registration-script |
| `client/API mismatch: …` (exit 2) | `check_compatibility` found the server's record schema newer than the installed client | Upgrade the client, then regenerate the field reference | registration-script |
| `Blocked: <script> would write to production catalog <url> with no passing dry run there for the current script and <config>. …` (or `… to an unrecognized (treated as production) catalog …`) | Prod guard hook: a non-dry run against a prod or `unknown` URL with no recorded passing `--dry-run` of the same script and config bytes against that same URL | Run `--dry-run` against the same `CATALOG_API_URL`, review, then rerun; any edit needs a new dry run | registration-script |
| `Blocked: <file> would contain a catalog API token …` | Secret guard hook | Read the token from the environment by name | auth |
| `Registration script lint failed for <file> …` | PostToolUse linter: template-owned code changed or a pipeline-safety rule broken | Apply each listed fix in the AGENT-EDITABLE region or `mapping.json` | registration-script |
| `catalog environment: <env> (<url>, from CATALOG_API_URL).` at session start | Printed every session: the catalog this session targets | Not an error; tell the user before reads or registration. On `prod`, it adds that writes are real records | auth |
| `catalog environment: none — CATALOG_API_URL is not set (auth skill).` | No catalog configured | Export the pair, restart Claude Code | auth |
| `catalog environment: unknown (<url>); the host names no dev/staging/prod, so treat it as production.` | The URL's host names no environment | Production rules apply; check the URL | auth |
| `catalog readiness: CATALOG_API_TOKEN is not set for <url> (auth skill).` | URL set, token not | Export the token, restart Claude Code | auth |
| `catalog readiness: …` (other) at session start | Client missing or old, or field reference stale | Follow the named skill | field-reference / registration-script |
