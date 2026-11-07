"""Shared helpers for the plugin's stdlib unittest suite."""

import json
import os
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "scripts"
TEMPLATE = PLUGIN_ROOT / "skills" / "registration-script" / "template" / "register.py"


def clean_env(**extra: str) -> dict[str, str]:
    """The current environment minus any catalog credentials, plus ``extra``."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("CATALOG_") and k != "CLAUDE_PLUGIN_DATA"
    }
    env.update(extra)
    return env


def run_script(
    path: Path,
    stdin: object = "",
    args: list[str] | None = None,
    env: dict | None = None,
    cwd=None,
):
    text = stdin if isinstance(stdin, str) else json.dumps(stdin)
    command = [sys.executable, str(path)] if path.suffix == ".py" else [str(path)]
    return subprocess.run(
        command + (args or []),
        check=False,
        input=text,
        capture_output=True,
        text=True,
        env=env if env is not None else clean_env(),
        cwd=cwd,
        timeout=60,
    )
