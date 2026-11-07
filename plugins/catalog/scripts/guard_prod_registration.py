#!/usr/bin/env python3
"""PreToolUse(Bash): block a production registration run that has no passing dry run against it.

Matches only a command that runs a file built from the registration template
(it carries the TEMPLATE-OWNED and AGENT-EDITABLE markers) without `--dry-run`.
The target catalog is an inline CATALOG_API_URL=... in the command, else the
session's CATALOG_API_URL. When that URL names prod, or no recognizable
environment, the run is allowed only if ${CLAUDE_PLUGIN_DATA}/dry_runs.json
records a passing dry run of the same script and config bytes against the same
URL (written by record_dry_run.py). Dev and staging runs, and malformed input,
are left to the normal permission flow.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _env import URL_VAR, env_from_url  # noqa: E402
from _hooklib import deny, is_registration_script, read_input  # noqa: E402

GUARDED_ENVS = {"prod", "unknown"}


def target_url(tokens: list[str]) -> str | None:
    inline = [t.split("=", 1)[1] for t in tokens if t.startswith(f"{URL_VAR}=")]
    url = inline[-1] if inline else os.environ.get(URL_VAR)
    return (url or "").strip().rstrip("/") or None


def config_arg(tokens: list[str], script: Path) -> Path:
    for index, token in enumerate(tokens):
        if token == "--config" and index + 1 < len(tokens):
            return Path(tokens[index + 1])
        if token.startswith("--config="):
            return Path(token.split("=", 1)[1])
    return script.with_name("mapping.json")


def template_scripts(tokens: list[str], cwd: Path) -> list[Path]:
    found = []
    for token in tokens:
        if not token.endswith(".py"):
            continue
        path = Path(token) if os.path.isabs(token) else cwd / token
        try:
            if path.is_file() and is_registration_script(
                path.read_text(errors="replace")
            ):
                found.append(path.resolve())
        except OSError:
            continue
    return found


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def passing_dry_run(script: Path, config: Path, url: str) -> bool:
    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data_dir:
        return False
    try:
        runs = json.loads((Path(data_dir) / "dry_runs.json").read_text())
    except (OSError, ValueError):
        return False
    per_script = runs.get(str(script)) if isinstance(runs, dict) else None
    entry = per_script.get(url) if isinstance(per_script, dict) else None
    if not isinstance(entry, dict):
        return False
    return (
        entry.get("script_sha256") == sha256(script)
        and entry.get("config") == str(config)
        and entry.get("config_sha256") == sha256(config)
    )


def main() -> int:
    data = read_input()
    if not data:
        return 0
    command = (data.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        return 0
    try:
        tokens = shlex.split(command)
    except ValueError:
        return 0
    url = target_url(tokens)
    if "--dry-run" in tokens or not url:
        return 0
    env = env_from_url(url)
    if env not in GUARDED_ENVS:
        return 0
    cwd = Path(data.get("cwd") or os.getcwd())
    for script in template_scripts(tokens, cwd):
        config = config_arg(tokens, script)
        config = (config if config.is_absolute() else cwd / config).resolve()
        if not passing_dry_run(script, config, url):
            label = (
                "production"
                if env == "prod"
                else "an unrecognized (treated as production)"
            )
            deny(
                f"Blocked: {script.name} would write to {label} catalog {url} with no passing dry run "
                f"there for the current script and {config.name}. Run it with --dry-run against the same "
                f"{URL_VAR} first (dev or staging before that), review the plan, then rerun. Editing either "
                "file after the dry run requires a new one."
            )
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
