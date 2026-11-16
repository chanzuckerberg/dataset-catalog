#!/usr/bin/env python3
"""PreToolUse(Write|Edit|MultiEdit): block writing a literal catalog API token into a file.

Denies only on a confident match: the value of a CATALOG_*TOKEN environment
variable, or a token-named key assigned a literal that looks like a real token.
Malformed input or anything else is allowed through untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _hooklib import deny, hardcoded_tokens, read_input  # noqa: E402


def written_text(tool_input: dict) -> str:
    parts = [tool_input.get("content"), tool_input.get("new_string")]
    for edit in tool_input.get("edits") or []:
        if isinstance(edit, dict):
            parts.append(edit.get("new_string"))
    return "\n".join(p for p in parts if isinstance(p, str))


def main() -> int:
    data = read_input()
    if not data or not isinstance(data.get("tool_input"), dict):
        return 0
    reasons = hardcoded_tokens(written_text(data["tool_input"]))
    if reasons:
        path = data["tool_input"].get("file_path", "the file")
        deny(
            f"Blocked: {path} would contain a catalog API token ({'; '.join(reasons)}). "
            "Read credentials from the environment by variable name (see the catalog-guide skill); never write the value."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
