#!/usr/bin/env bash
# Auth/preflight entry point: credentials, then a Python environment (created with uv when
# missing), then check_auth.py in that environment. Arguments pass through to check_auth.py.
#
# Python environment, first match wins: the active $VIRTUAL_ENV, ./.venv, or a new ./.venv made
# with `uv venv` plus the latest released catalog-client. Without uv, the check still runs on the
# system python3 (it is stdlib-only) and says how to get uv.
#
# Exit codes follow check_auth.py; 2 when CATALOG_API_URL or CATALOG_API_TOKEN is unset.
# With --report everything goes to stdout and the exit code is always 0 (slash-command injection).
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="https://github.com/chanzuckerberg/dataset-catalog"
report=0
for arg in "$@"; do [ "$arg" = "--report" ] && report=1; done

say() { if [ "$report" -eq 1 ]; then echo "$*"; else echo "$*" >&2; fi; }
finish() { if [ "$report" -eq 1 ]; then exit 0; else exit "$1"; fi; }

missing=()
[ -n "${CATALOG_API_URL:-}" ] || missing+=(CATALOG_API_URL)
[ -n "${CATALOG_API_TOKEN:-}" ] || missing+=(CATALOG_API_TOKEN)
if [ "${#missing[@]}" -gt 0 ]; then
  names="${missing[0]}"
  [ "${#missing[@]}" -eq 2 ] && names="${missing[0]} and ${missing[1]}"
  say "check_auth: $names not set. Export CATALOG_API_URL and CATALOG_API_TOKEN for the catalog you want (catalog-guide skill), then restart Claude Code."
  finish 2
fi

latest_client_tag() {
  git ls-remote --tags --refs "$repo" 'catalog-client-v*' 2>/dev/null |
    sed 's#.*refs/tags/##' | sort -V | tail -n 1
}

venv="$PWD/.venv"
if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
  python="$VIRTUAL_ENV/bin/python"
elif [ -x "$venv/bin/python" ]; then
  python="$venv/bin/python"
elif command -v uv >/dev/null 2>&1; then
  say "check_auth: no Python environment here; creating $venv with uv."
  if ! uv venv --quiet --python ">=3.11" "$venv" >&2; then
    say "check_auth: uv could not create $venv."
    finish 1
  fi
  python="$venv/bin/python"
  tag="$(latest_client_tag)"
  if [ -n "$tag" ] && uv pip install --quiet --python "$python" \
    "catalog-client @ git+$repo.git@$tag#subdirectory=dataset-catalog-client" >&2; then
    say "check_auth: installed catalog-client ${tag#catalog-client-v} into $venv."
  else
    say "check_auth: could not install catalog-client into $venv (registration-script skill, installing the client); continuing with the access check."
  fi
else
  say "check_auth: no Python environment and uv is not installed (https://docs.astral.sh/uv/getting-started/installation/); running the access check with the system python3."
  python="$(command -v python3 || true)"
  if [ -z "$python" ]; then
    say "check_auth: python3 not found."
    finish 1
  fi
fi

exec "$python" "$here/check_auth.py" "$@"
