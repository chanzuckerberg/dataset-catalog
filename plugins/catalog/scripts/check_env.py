#!/usr/bin/env python3
"""SessionStart readiness check for the catalog plugin.

Without any network call: names the catalog environment the session points at
(from CATALOG_API_URL), then checks that a token is set, catalog-client is
installed and new enough for the registration template, and the field
reference is not older than the installed client. Prints one environment line,
plus one line per problem for Claude to relay when relevant. Always exits 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from _env import (  # noqa: E402
    TOKEN_VAR,
    URL_VAR,
    catalog_settings,
    client_version,
    env_from_url,
    version_tuple,
)

FIELDS_JSON = PLUGIN_ROOT / "skills" / "field-reference" / "fields.json"
MIN_CLIENT = "1.3.0"


def environment_line() -> str:
    url, _ = catalog_settings()
    if not url:
        return f"catalog environment: none — {URL_VAR} is not set (auth skill)."
    env = env_from_url(url)
    if env == "unknown":
        return (
            f"catalog environment: unknown ({url}); the host names no dev/staging/prod, so treat it "
            "as production."
        )
    line = f"catalog environment: {env} ({url}, from {URL_VAR})."
    if env == "prod":
        line += " Writes here are real records; try new scripts against dev or staging first."
    return line


def problems() -> list[str]:
    found = []
    url, token = catalog_settings()
    if url and not token:
        found.append(f"{TOKEN_VAR} is not set for {url} (auth skill).")
    installed = client_version()
    if not installed:
        found.append(
            "catalog-client is not installed here; registration scripts and the `catalog` CLI need it "
            "(install steps: registration-script skill)."
        )
    elif version_tuple(installed) < version_tuple(MIN_CLIENT):
        found.append(
            f"catalog-client {installed} is older than {MIN_CLIENT}, which the registration template requires; "
            "upgrade before running a generated script (registration-script skill)."
        )
    if installed:
        try:
            stamp = json.loads(FIELDS_JSON.read_text())["stamp"].get("client_version")
        except (OSError, ValueError, KeyError, AttributeError):
            stamp = None
        if stamp and version_tuple(installed) > version_tuple(stamp):
            found.append(
                f"the field reference was generated from catalog-client {stamp} but {installed} is installed; "
                "fields may be missing — see the field-reference skill on staleness."
            )
    return found


def main() -> int:
    try:
        lines = [environment_line()] + [f"catalog readiness: {p}" for p in problems()]
    except Exception:  # noqa: BLE001 - a readiness hint must never break session start
        return 0
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
