#!/usr/bin/env python3
"""PreToolUse(Bash): block a production registration run that has no passing production dry run.

Matches only a command that runs a file built from the registration template
(it carries the TEMPLATE-OWNED and AGENT-EDITABLE markers) with `--env prod`
and without `--dry-run`. It is allowed when ${CLAUDE_PLUGIN_DATA}/dry_runs.json
records a passing `--env prod --dry-run` of the same script and config bytes
(written by record_dry_run.py). Everything else, including malformed input, is
left to the normal permission flow.
"""

import hashlib
import json
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _hooklib import deny, is_registration_script, read_input  # noqa: E402

PROD_VALUES = {"prod", "production"}


def env_arg(tokens: list[str]) -> str | None:
    for index, token in enumerate(tokens):
        if token == "--env" and index + 1 < len(tokens):
            return tokens[index + 1].lower()
        if token.startswith("--env="):
            return token.split("=", 1)[1].lower()
    return None


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


def passing_dry_run(script: Path, config: Path) -> bool:
    data_dir = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data_dir:
        return False
    try:
        runs = json.loads((Path(data_dir) / "dry_runs.json").read_text())
    except (OSError, ValueError):
        return False
    per_script = runs.get(str(script)) if isinstance(runs, dict) else None
    entry = per_script.get("prod") if isinstance(per_script, dict) else None
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
    if env_arg(tokens) not in PROD_VALUES or "--dry-run" in tokens:
        return 0
    cwd = Path(data.get("cwd") or os.getcwd())
    for script in template_scripts(tokens, cwd):
        config = config_arg(tokens, script)
        config = (config if config.is_absolute() else cwd / config).resolve()
        if not passing_dry_run(script, config):
            deny(
                f"Blocked: {script.name} --env prod has no passing production dry run for the current script "
                f"and {config.name}. Run it with --env prod --dry-run first (staging before that), review the "
                "plan, then rerun. Editing either file after the dry run requires a new one."
            )
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
