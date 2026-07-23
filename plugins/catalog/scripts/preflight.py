#!/usr/bin/env python3
"""Shared preflight for the catalog plugin — run ONCE before query or register work.

All three skills (catalog-read, catalog-search, catalog-register) need the same thing up front: a
reachable catalog and a working token. This script checks that in one place so a
missing or expired token fails fast with clear guidance, instead of surfacing
three steps into a task (after an expensive OLS expansion, or a full schema
mapping right before --submit).

It is read-only and never prints the token, so the catalog plugin's PreToolUse
hook auto-approves it — running it needs no permission prompt.

    python preflight.py            # verify config AND confirm the token works (authed GET)
    python preflight.py --no-ping  # config presence only, no network call

Config (environment — same contract as the catalog CLI / SDK / query scripts):
    CATALOG_API_URL    base URL; defaults to production when unset.
    CATALOG_API_TOKEN  API token; required. Issue at <url>/tokens in a logged-in
                       browser (SSO-gated) and store it in your Claude Code env
                       settings — never on a command line.

Exit codes: 0 = ready; 2 = misconfigured or token rejected (guidance on stderr).
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
from typing import NoReturn

# Kept in sync with catalog_client / the query scripts' _catalog.DEFAULT_API_URL.
DEFAULT_API_URL = "https://datacatalog.prod-sci-data.prod.czi.team/"
# Cheapest authed read: one dataset. Confirms host + token without paginating.
PING_PATH = "/api/datasets/?limit=1"
TIMEOUT = 15.0
EXIT_MISCONFIGURED = 2


def _fail(message: str) -> NoReturn:
    """Print guidance and exit non-zero — a real misconfiguration, stop here."""
    print(f"preflight: {message}", file=sys.stderr)
    raise SystemExit(EXIT_MISCONFIGURED)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="preflight",
        description="Verify the catalog is reachable and the token works, once, "
        "before query or register work. Read-only; never prints the token.",
    )
    parser.add_argument(
        "--no-ping",
        action="store_true",
        help="check config presence only; skip the authed connectivity GET",
    )
    args = parser.parse_args(argv)

    configured_url = os.environ.get("CATALOG_API_URL")
    url = (configured_url or DEFAULT_API_URL).rstrip("/")
    token = os.environ.get("CATALOG_API_TOKEN")

    if not token:
        _fail(
            "CATALOG_API_TOKEN is not set. Issue a token at "
            f"{url}/tokens (open in a logged-in browser; the page is SSO-gated), "
            "then set CATALOG_API_TOKEN in your Claude Code env settings — never "
            "paste it into a command or the chat."
        )

    origin = "" if configured_url else " (default: production)"
    print(f"preflight: CATALOG_API_URL = {url}{origin}")
    print("preflight: CATALOG_API_TOKEN = set (redacted)")

    if args.no_ping:
        print("preflight: config present; connectivity unchecked (--no-ping).")
        return 0

    # Authed GET — the token travels as a header, never on the command line, and
    # this catches an expired/wrong token that a presence check would miss.
    request = urllib.request.Request(
        f"{url}{PING_PATH}",
        headers={"X-catalog-api-token": token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            _fail(
                f"catalog rejected the token (HTTP 401) at {url}. It is likely "
                f"expired or wrong — reissue at {url}/tokens and update your env."
            )
        _fail(
            f"catalog returned HTTP {exc.code} for {PING_PATH}; "
            "check CATALOG_API_URL points at a valid catalog instance."
        )
    except urllib.error.URLError as exc:
        # A network problem is not a config error — warn, but don't block the task.
        print(
            f"preflight: warning — could not reach {url} ({exc.reason}); config "
            "looks set, but connectivity is unverified.",
            file=sys.stderr,
        )
        return 0

    print(f"preflight: catalog reachable, token accepted (HTTP {status}). Ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
