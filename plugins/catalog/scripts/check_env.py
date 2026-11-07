#!/usr/bin/env python3
"""SessionStart readiness check for the catalog plugin. Silent when everything is in order.

Checks, without any network call: catalog-client is installed and new enough
for the registration template, the field reference is not older than the
installed client, and a staging token is present. Each problem prints one line
for Claude to relay when it becomes relevant. Always exits 0.
"""

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

from _env import (  # noqa: E402
    DEFAULT_ENV,
    client_version,
    resolve_token,
    token_var_names,
    version_tuple,
)

FIELDS_JSON = PLUGIN_ROOT / "skills" / "field-reference" / "fields.json"
MIN_CLIENT = "1.3.0"


def problems() -> list[str]:
    found = []
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
    if resolve_token(DEFAULT_ENV)[1] is None:
        found.append(
            f"no {DEFAULT_ENV} token: set {token_var_names(DEFAULT_ENV)[0]} before catalog work (auth skill)."
        )
    return found


def main() -> int:
    try:
        found = problems()
    except Exception:  # noqa: BLE001 - a readiness hint must never break session start
        return 0
    for line in found:
        print(f"catalog readiness: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
