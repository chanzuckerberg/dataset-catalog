# Generated scripts and hooks

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
