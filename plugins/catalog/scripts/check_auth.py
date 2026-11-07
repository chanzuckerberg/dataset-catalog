#!/usr/bin/env python3
"""Report which catalog environment you are pointed at and what your token can do.

    check_auth.py [staging|prod] [--verbose]

Prints environment, catalog URL, token source (the variable NAME, never the
value), identity, read/write permission, expiry, and the installed client
version. Read-only: it never attempts a write to probe permissions.

Exit codes: 0 = token works for reads; 1 = catalog unreachable or unexpected
response; 2 = no token, unknown environment, or token rejected.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _env import (  # noqa: E402
    ENVIRONMENTS,
    client_version,
    normalize_env,
    resolve_token,
    token_var_names,
)

TIMEOUT = 15.0
VALIDATE_PATH = "/api/v1/token/validate"
LEGACY_VALIDATE_PATH = "/token/validate"
READ_PROBE_PATH = "/api/v1/datasets/?limit=1"
EXIT_UNREACHABLE = 1
EXIT_AUTH = 2


class Unreachable(Exception):
    pass


def get(url: str, token: str) -> tuple[int, object]:
    """GET with the token header; return (status, parsed JSON or None)."""
    request = urllib.request.Request(
        url, headers={"X-catalog-api-token": token, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            status, body = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise Unreachable(str(getattr(exc, "reason", exc))) from exc
    try:
        return status, json.loads(body.decode("utf-8"))
    except ValueError:
        return status, None  # an SSO login page is HTML


def permissions(value: object) -> tuple[str, str]:
    # null predates permission recording; the API treats those tokens as read-only.
    if value == "rw":
        return "yes", "yes"
    return "yes", "no"


def check(env: str, verbose: bool) -> tuple[list[tuple[str, str]], int]:
    url = ENVIRONMENTS[env]
    rows = [("environment", env), ("catalog URL", url)]
    var, token = resolve_token(env)
    version = client_version() or "not installed"
    if not token:
        specific, generic = token_var_names(env)
        rows += [
            (
                "token source",
                f"none — set {specific} (or {generic} with CATALOG_API_URL={url})",
            ),
            ("read", "no"),
            ("write", "no"),
            ("client version", version),
        ]
        return rows, EXIT_AUTH
    rows.append(("token source", var or ""))

    status, body = get(url + VALIDATE_PATH, token)
    if status == 200 and isinstance(body, dict) and "token" in body:
        tok, user = body.get("token") or {}, body.get("user") or {}
        identity = user.get("name") or "unknown"
        if user.get("team"):
            identity += f" ({user['team']})"
        if verbose and user.get("email"):
            identity += f" <{user['email']}>"
        read, write = permissions(tok.get("permissions"))
        if tok.get("is_active") is False:
            read, write = "no (token inactive)", "no"
        rows += [
            ("identity", identity),
            ("token name", tok.get("name") or "unnamed"),
            ("read", read),
            ("write", write),
            ("expires", tok.get("expires_at") or "never"),
        ]
        if verbose:
            rows.append(("last used", tok.get("last_used_at") or "never"))
        rows.append(("client version", version))
        return rows, 0 if read == "yes" else EXIT_AUTH
    if status == 401:
        detail = body.get("detail") if isinstance(body, dict) else None
        rows += [
            ("identity", "unknown"),
            ("read", f"no — token rejected (HTTP 401: {detail or 'unauthorized'})"),
            ("write", "no"),
            ("client version", version),
        ]
        return rows, EXIT_AUTH
    if status != 404:
        raise Unreachable(f"{VALIDATE_PATH} returned HTTP {status}")

    # Deployment predates the v1 validate route.
    identity, expires, write = "unknown", "unknown", f"unknown — needs {VALIDATE_PATH}"
    legacy_status, legacy = get(url + LEGACY_VALIDATE_PATH, token)
    if (
        legacy_status == 200
        and isinstance(legacy, dict)
        and isinstance(legacy.get("user"), dict)
    ):
        user = legacy["user"]
        identity = user.get("name") or identity
        if user.get("team"):
            identity += f" ({user['team']})"
        tok = legacy.get("token") or {}
        expires = tok.get("expires_at") or expires
        if "permissions" in tok:
            write = permissions(tok["permissions"])[1]
    probe_status, probe = get(url + READ_PROBE_PATH, token)
    if probe_status == 200:
        read, code = "yes", 0
    elif probe_status == 401:
        detail = probe.get("detail") if isinstance(probe, dict) else None
        read, write, code = (
            f"no — token rejected (HTTP 401: {detail or 'unauthorized'})",
            "no",
            EXIT_AUTH,
        )
    else:
        raise Unreachable(f"{READ_PROBE_PATH} returned HTTP {probe_status}")
    rows += [
        ("identity", identity),
        ("read", read),
        ("write", write),
        ("expires", expires),
        ("client version", version),
    ]
    return rows, code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check catalog environment and token permissions."
    )
    parser.add_argument("env", nargs="?", help="staging (default) or prod")
    parser.add_argument(
        "--verbose", action="store_true", help="also print email and last-used time"
    )
    # Slash-command shell injection aborts on a non-zero exit, which would hide the very report it needs.
    parser.add_argument(
        "--report",
        action="store_true",
        help="always exit 0; the report carries the outcome",
    )
    args = parser.parse_args(argv)
    code = run(args)
    return 0 if args.report else code


def run(args: argparse.Namespace) -> int:
    # In --report mode errors go to stdout so the slash command shows them.
    err = sys.stdout if args.report else sys.stderr
    try:
        env = normalize_env(args.env)
    except ValueError as exc:
        print(f"check_auth: {exc}", file=err)
        return EXIT_AUTH
    try:
        rows, code = check(env, args.verbose)
    except Unreachable as exc:
        print(
            f"check_auth: could not reach {ENVIRONMENTS[env]} ({exc}). Check network/VPN.",
            file=err,
        )
        return EXIT_UNREACHABLE
    width = max(len(key) for key, _ in rows)
    for key, value in rows:
        print(f"{key.ljust(width)}  {value}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
