#!/usr/bin/env python3
"""PostToolUse(Bash): remember registration dry runs that passed.

A generated script prints `catalog-dry-run: ok env=... script=... script_sha256=...
config=... config_sha256=...` only when every record planned cleanly. This
records that line in ${CLAUDE_PLUGIN_DATA}/dry_runs.json, after re-hashing the
files so a line copied from elsewhere cannot vouch for different bytes.
guard_prod_registration.py reads it. Silent; malformed input is ignored.
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _hooklib import DRY_RUN_RE, read_input  # noqa: E402


def output_text(response: object) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        return "\n".join(str(response.get(key) or "") for key in ("stdout", "output"))
    return ""


def sha256(path: str) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def main() -> int:
    data = read_input()
    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data or not data_dir:
        return 0
    matches = [
        m
        for m in DRY_RUN_RE.finditer(output_text(data.get("tool_response")))
        if sha256(m["script"]) == m["script_sha"]
        and sha256(m["config"]) == m["config_sha"]
    ]
    if not matches:
        return 0
    store = Path(data_dir) / "dry_runs.json"
    try:
        runs = json.loads(store.read_text())
        if not isinstance(runs, dict):
            runs = {}
    except (OSError, ValueError):
        runs = {}
    for m in matches:
        per_script = runs.get(m["script"])
        if not isinstance(per_script, dict):
            per_script = runs[m["script"]] = {}
        per_script[m["env"]] = {
            "script_sha256": m["script_sha"],
            "config": m["config"],
            "config_sha256": m["config_sha"],
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(runs, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
