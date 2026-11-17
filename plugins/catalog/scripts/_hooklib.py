"""Helpers shared by the plugin's hook scripts (stdlib only)."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PLUGIN_ROOT / "skills" / "registration-script" / "template" / "register.py"
OWNED_MARKER = "# === TEMPLATE-OWNED"
EDITABLE_MARKER = "# === AGENT-EDITABLE ==="
END_EDITABLE_MARKER = "# === END AGENT-EDITABLE ==="
CLIENT_PIN = "catalog-client>=1.3.0,<2"
DRY_RUN_RE = re.compile(
    r"catalog-dry-run: ok env=(?P<env>\S+) url=(?P<url>\S+) script=(?P<script>.+?) script_sha256=(?P<script_sha>[0-9a-f]{64}) "
    r"config=(?P<config>.+?) config_sha256=(?P<config_sha>[0-9a-f]{64})\s*$",
    re.MULTILINE,
)

_PLACEHOLDER = re.compile(
    r"(?i)^(x+|\*+|\.+|<.*>|\$\{.*\}|\$\w+|your[-_].*|changeme|example.*|redacted|none|null|token)$"
)
_TOKEN_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?:catalog[_-]?(?:\w+[_-])?api[_-]?token|api[_-]?token|x-catalog-api-token)
    ["']?\s*[:=]\s*["']([^"'\s]{16,})["']
    """
)
# A bare `token` key is ambiguous (pagination cursors, CSRF), so it needs a value shaped like an issued API token.
_BARE_TOKEN_ASSIGNMENT = re.compile(
    r"""(?i)(?<![\w-])token["']?\s*[:=]\s*["']([A-Za-z0-9_\-]{32,})["']"""
)
_ENV_ASSIGNMENT = re.compile(
    r"(?m)^\s*(?:export\s+)?CATALOG_[A-Z_]*TOKEN\s*=\s*([^\s#\"']{16,})\s*$"
)


def read_input() -> dict | None:
    """Hook event JSON from stdin, or None when it is malformed (callers then do nothing)."""
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def emit(payload: dict) -> None:
    print(json.dumps(payload))


def deny(reason: str) -> None:
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def _looks_secret(value: str) -> bool:
    if _PLACEHOLDER.match(value) or "os.environ" in value or "getenv" in value:
        return False
    return (
        bool(re.fullmatch(r"[A-Za-z0-9_\-.~+/=]+", value))
        and bool(re.search(r"\d", value))
        and bool(re.search(r"[A-Za-z]", value))
    )


def hardcoded_tokens(text: str) -> list[str]:
    """Reasons text carries a literal catalog token. Only confident matches."""
    reasons = []
    for name, value in os.environ.items():
        if (
            re.fullmatch(r"CATALOG_\w*TOKEN", name)
            and len(value) >= 12
            and value in text
        ):
            reasons.append(f"contains the value of ${name}")
    for match in list(_TOKEN_ASSIGNMENT.finditer(text)) + list(
        _ENV_ASSIGNMENT.finditer(text)
    ):
        if _looks_secret(match.group(1)):
            line = text.count("\n", 0, match.start()) + 1
            reasons.append(f"line {line} assigns a literal API token")
    for match in _BARE_TOKEN_ASSIGNMENT.finditer(text):
        value = match.group(1)
        if all(re.search(p, value) for p in (r"[a-z]", r"[A-Z]", r"\d")):
            line = text.count("\n", 0, match.start()) + 1
            reasons.append(f"line {line} assigns a literal API token")
    return reasons


def is_registration_script(text: str) -> bool:
    return OWNED_MARKER in text and EDITABLE_MARKER in text


def split_regions(text: str) -> tuple[str, str, str] | None:
    """(owned head, agent-editable body, owned tail); None if the markers are missing or out of order."""
    start = text.find(OWNED_MARKER)
    editable = text.find(EDITABLE_MARKER)
    end = text.find(END_EDITABLE_MARKER)
    if start < 0 or editable < start or end < editable:
        return None
    return text[start:editable], text[editable:end], text[end:]


def header(text: str) -> str:
    start = text.find(OWNED_MARKER)
    return text[:start] if start >= 0 else ""
