"""Catalog connection settings and environment naming shared by the plugin scripts.

There is no built-in default environment: everything uses CATALOG_API_URL and
CATALOG_API_TOKEN from the environment, and names the environment from the
URL's hostname. The generated registration template carries its own copy of
env_from_url() (it must run without the plugin); tests keep the two identical.
"""

from __future__ import annotations

import os
import re
import urllib.parse

URL_VAR = "CATALOG_API_URL"
TOKEN_VAR = "CATALOG_API_TOKEN"


def env_from_url(url: str) -> str:
    """'dev', 'staging' or 'prod' from the URL's hostname; 'unknown' when it names none or several."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    aliases = {"production": "prod", "stage": "staging", "development": "dev"}
    labels = {aliases.get(label, label) for label in re.split(r"[.-]", host)}
    found = labels & {"dev", "staging", "prod"}
    return found.pop() if len(found) == 1 else "unknown"


def catalog_settings() -> tuple[str | None, str | None]:
    """(CATALOG_API_URL without trailing slash, CATALOG_API_TOKEN); either may be None."""
    url = (os.environ.get(URL_VAR) or "").strip().rstrip("/") or None
    return url, os.environ.get(TOKEN_VAR) or None


def client_version() -> str | None:
    """Installed catalog-client version in this interpreter, else via the `catalog` CLI's interpreter."""
    import importlib.metadata
    import shutil
    import subprocess

    try:
        return importlib.metadata.version("catalog-client")
    except importlib.metadata.PackageNotFoundError:
        pass
    cli = shutil.which("catalog")
    if not cli:
        return None
    try:
        with open(cli, encoding="utf-8", errors="replace") as handle:
            shebang = handle.readline()
    except OSError:
        return None
    if not shebang.startswith("#!"):
        return None
    interpreter = shebang[2:].strip().split()
    try:
        result = subprocess.run(
            [
                *interpreter,
                "-c",
                "import importlib.metadata as m; print(m.version('catalog-client'))",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def version_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for piece in version.lstrip("v").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)
