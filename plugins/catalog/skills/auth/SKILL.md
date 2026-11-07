---
name: auth
description: Getting and checking access to the Scientific Dataset Catalog — issuing an API token, which environment variable holds it, checking read and write permission, getting write access, pipeline credentials versus personal tokens, storing tokens safely, expiry and rotation. Use when a token is missing, rejected, or read-only, when asked "how do I get access?", "can I write?", or how a pipeline should authenticate.
model: sonnet
---

# Access and credentials

## Environments

| `--env` | URL | Use for |
|---|---|---|
| `staging` (default everywhere in this plugin) | `https://datacatalog.staging-sci-data.staging.czi.team` | Trying things, dry runs, first registrations |
| `prod` | `https://datacatalog.prod-sci-data.prod.czi.team` | Real records, after a passing staging run |

Tokens are per environment: a staging token is rejected by prod.

## Getting a token

Open `<catalog URL>/tokens` in a browser where you are logged in (SSO). Create a token; the value is
shown once, so store it immediately (below). Never paste a token into chat, a command line, code, or
a file in the repo; a plugin hook blocks writing one into a file.

## Where the token goes

| Variable | Read by |
|---|---|
| `CATALOG_STAGING_API_TOKEN`, `CATALOG_PROD_API_TOKEN` | Plugin scripts (`/catalog:whoami`) and generated registration scripts, for that `--env` |
| `CATALOG_API_TOKEN` + `CATALOG_API_URL` | The `catalog` CLI and SDK examples; plugin and generated scripts also accept this pair when `CATALOG_API_URL` is exactly that environment's URL |

The per-environment names exist so a prod token never has to be in the session or shell where
you experiment. Set staging in your Claude Code environment settings; keep the prod token out of
Claude Code entirely and give it only to the pipeline that runs production registrations (the
repo README has recommended `settings.json` deny rules).

## Checking access

`/catalog:whoami [env]`, or `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_auth.py" [env]` when you run
it yourself, reports: environment, URL, which variable supplied
the token (never its value), identity, read and write permission, expiry, client version.

- **write** comes from the token's recorded permissions: `rw` = can write; `r` = read-only; tokens
  issued before permissions were recorded count as read-only.
- `write: unknown — needs /api/v1/token/validate` means the deployment predates that route. The
  check never attempts a write to find out; treat write as unconfirmed until a real (staging)
  registration succeeds or the route ships.
- Exit codes: 0 reads work, 1 catalog unreachable, 2 no token / rejected / unknown environment.

## Getting write access

Write permission is fixed **when the token is issued**: joining the right group later does not upgrade
an existing token. After write access is granted, issue a new token and replace the old one.

TODO(owner): document the access-request process — who approves write access per environment,
the request form or channel, and the expected turnaround. Until then, tell the user to ask the
catalog team and do not invent a process.

## Pipelines

- Use a dedicated credential for the pipeline (a service account or a token issued for that
  purpose), not a person's token: it survives people leaving and can be revoked alone.
  TODO(owner): name the supported service-account mechanism, if one exists.
- Inject it as an environment variable from the scheduler's secrets store or a secrets manager;
  generated scripts read it by name and never prompt.
- Least privilege: read-only tokens for anything that only searches; write tokens only for the
  registration job, per environment.
- Expiry: `/catalog:whoami` shows `expires`. Rotate before expiry: issue the new token, update the
  secret, confirm with `whoami`, then revoke the old one on the `/tokens` page. Revoke immediately if
  a token is ever exposed.

Errors such as `Invalid or expired token`: `common-errors`.
