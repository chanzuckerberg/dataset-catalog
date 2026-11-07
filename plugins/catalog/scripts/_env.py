"""Catalog environments and credential lookup shared by the plugin scripts.

The generated registration template carries its own copy of this mapping (it
must run without the plugin), so keep the two in step.
"""

import os

ENVIRONMENTS = {
    "staging": "https://datacatalog.staging-sci-data.staging.czi.team",
    "prod": "https://datacatalog.prod-sci-data.prod.czi.team",
}
DEFAULT_ENV = "staging"
ALIASES = {"production": "prod", "stage": "staging"}


def normalize_env(name: str | None) -> str:
    env = (name or DEFAULT_ENV).strip().lower()
    env = ALIASES.get(env, env)
    if env not in ENVIRONMENTS:
        raise ValueError(
            f"unknown environment {name!r}; expected one of: {', '.join(ENVIRONMENTS)}"
        )
    return env


def token_var_names(env: str) -> list[str]:
    return [f"CATALOG_{env.upper()}_API_TOKEN", "CATALOG_API_TOKEN"]


def resolve_token(env: str) -> tuple[str | None, str | None]:
    """Return (variable name, token) for ``env``, or (None, None).

    ``CATALOG_<ENV>_API_TOKEN`` wins. The generic ``CATALOG_API_TOKEN`` is used
    only when ``CATALOG_API_URL`` names this same environment, so a token
    issued for one environment is never sent to another.
    """
    specific, generic = token_var_names(env)
    if os.environ.get(specific):
        return specific, os.environ[specific]
    url = (os.environ.get("CATALOG_API_URL") or "").rstrip("/")
    if os.environ.get(generic) and url == ENVIRONMENTS[env]:
        return generic, os.environ[generic]
    return None, None


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
