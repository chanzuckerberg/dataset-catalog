---
name: auth
description: Getting and checking access to the Scientific Dataset Catalog — which catalog environment you are pointed at, issuing an API token, the environment variables that hold the URL and token, checking read and write permission, getting write access, pipeline credentials versus personal tokens, storing tokens safely, expiry and rotation. Use when a token is missing, rejected, or read-only, when asked "how do I get access?", "can I write?", "which catalog am I using?", how to switch environments, or how a pipeline should authenticate.
model: sonnet
---

# Access and credentials

## Environments

Everything (plugin scripts, generated registration scripts, the `catalog` CLI, the SDK) uses one
pair: `CATALOG_API_URL` and `CATALOG_API_TOKEN`. Whatever catalog that pair names is the one used;
there is no default. The environment name is read from the URL's hostname:

| Environment | Host | Use for |
|---|---|---|
| `dev` | `*.dev-sci-data.dev.czi.team` (per-deployment previews) | Trying things against a preview build |
| `staging` | `https://datacatalog.staging-sci-data.staging.czi.team` | Trying things, dry runs, first registrations |
| `prod` | `https://datacatalog.prod-sci-data.prod.czi.team` | Real records, after a passing dev or staging run |
| `unknown` | A host naming none of the above | Treated as production |

Tokens are per environment: a staging token is rejected by prod. Try new work against dev or
staging first.

**Switching**: change both variables (and restart Claude Code if you changed your shell init file,
below), or prefix a single command without putting the token value on the line:

```bash
CATALOG_API_URL=https://datacatalog.staging-sci-data.staging.czi.team \
CATALOG_API_TOKEN="$(cat ~/.config/catalog/staging-token)" python register.py --dry-run
```

Whenever you run the access check below, and before any registration run, tell the user which
environment and URL it targets.

## Getting a token

Open `<catalog URL>/tokens` in a browser where you are logged in (SSO). Create a token; the value is
shown once, so store it immediately (below). Never paste a token into chat, a command line, code, or
a file in the repo; a plugin hook blocks writing one into a file.

## Where the token goes

Export both variables from your shell init file: `~/.zshrc` for zsh (the macOS default), `~/.bashrc`
for bash (most HPC login nodes). Claude Code reads the shell environment at startup and sources
those files for its Bash tool, so the same values reach your terminal, pipelines started from it,
and Claude Code alike.

The URL is plain config:

```bash
export CATALOG_API_URL=https://datacatalog.staging-sci-data.staging.czi.team
```

Prefer not to store the raw token in the rc file; rc files often live in a dotfiles repo.

- **macOS**: keep it in Keychain. Once, run
  `security add-generic-password -a "$USER" -s catalog-api-token -w` (it prompts for the value, so
  it stays out of shell history), then in `~/.zshrc`:

  ```bash
  export CATALOG_API_TOKEN="$(security find-generic-password -a "$USER" -s catalog-api-token -w 2>/dev/null)"
  ```

- **Linux/HPC**: a `chmod 600` file outside any repo, e.g. `~/.config/catalog/token`, then in
  `~/.bashrc`: `export CATALOG_API_TOKEN="$(cat ~/.config/catalog/token)"`.
- **Fallback**: a plain `export CATALOG_API_TOKEN=…` line only if the rc file is not in a repo; add
  it with an editor, not an `echo` that lands in shell history.

After editing, open a new terminal (or `source` the file) and **restart Claude Code**. The desktop
app (v2.1.304+) reads the login shell's exports at launch: quit and reopen it. The VS Code extension
inherits them only when VS Code is launched from a terminal (`code .`). In an SSH session Claude
Code does not get variables from those files; export them in that session before starting it.

**Not in Claude Code `settings.json` `env`.** Values there are stored in plaintext and reach only
Claude Code sessions and the processes they start, so the same registration script behaves
differently inside and outside Claude. `.claude/settings.json` is meant to be committed, so a token
there leaks into git; `.claude/settings.local.json` is auto-gitignored only when Claude Code itself
creates it ([settings reference](https://code.claude.com/docs/en/settings-reference.md#env)).

Never put a token in chat, on a command line, in code, in a committed file, or in Claude Code
settings. Keep production tokens out of the shell Claude Code runs in; give them only to the
pipeline that runs production registrations (the repo README has recommended deny rules).

## Checking access

`/catalog:whoami`, or `"${CLAUDE_PLUGIN_ROOT}/scripts/check_auth.sh"` when you run it
yourself (`--verbose` adds email and last use), works in three steps:

1. **Credentials**: stops with exit 2 if `CATALOG_API_URL` or `CATALOG_API_TOKEN` is unset, before
   touching Python.
2. **Python environment**: uses the active virtual environment, else `./.venv`, else creates
   `./.venv` with `uv venv` and installs the latest released `catalog-client` into it. Without uv it
   says how to get it and runs the check on the system `python3`.
3. **The check** (`check_auth.py`, in that environment), which reports: `environment <env> (from CATALOG_API_URL)`
first, then URL, which variable supplied the token (never its value), identity, read and write
permission, expiry, client version. State the environment to the user every time.

- **write** comes from the token's recorded permissions: `rw` = can write; `r` = read-only; tokens
  issued before permissions were recorded count as read-only.
- `write: unknown — needs /api/v1/token/validate` means the deployment predates that route. The
  check never attempts a write to find out; treat write as unconfirmed until a real (dev or staging)
  registration succeeds or the route ships.
- Exit codes: 0 reads work, 1 catalog unreachable, 2 URL or token not set, or token rejected.

The session-start readiness check prints one `catalog environment: …` line every session (no
network call); relay it when the user is about to read or register.

## Getting write access

Write access comes from membership in the `sci-data-curation` team:

1. In Okta, open **Request access**.
2. Search for **Teams**, and in Teams find `sci-data-curation`.
3. Request to be added to that team.
4. Once you have been added, issue a new token (see "Getting a token") and replace the old one
   wherever it is stored. Confirm with `/catalog:whoami` that `write` is now `yes`.

Write permission is fixed **when the token is issued**: joining the team does not upgrade an existing
token, so step 4 is required.

## Pipelines

- Use a dedicated credential for the pipeline (a service account or a token issued for that
  purpose), not a person's token: it survives people leaving and can be revoked alone.
  TODO(owner): name the supported service-account mechanism, if one exists.
- Inject `CATALOG_API_URL` and `CATALOG_API_TOKEN` as environment variables from the scheduler's
  secrets store or a secrets manager, not from a person's rc file: batch jobs may not source
  `~/.bashrc`. Generated scripts read them by name and never prompt.
- Least privilege: read-only tokens for anything that only searches; write tokens only for the
  registration job, per environment.
- Expiry: `/catalog:whoami` shows `expires`. Rotate before expiry: issue the new token, update the
  secret, confirm with `whoami`, then revoke the old one on the `/tokens` page. Revoke immediately if
  a token is ever exposed.

Errors such as `Invalid or expired token`: `common-errors`.
