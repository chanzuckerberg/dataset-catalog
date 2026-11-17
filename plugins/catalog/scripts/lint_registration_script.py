#!/usr/bin/env python3
"""Lint a registration script built from the plugin template against the pipeline-safety rules.

    lint_registration_script.py PATH          # CLI: prints problems, exit 1 if any
    (as a PostToolUse hook)                   # reads the hook event JSON from stdin

Applies only to files carrying the template's TEMPLATE-OWNED / AGENT-EDITABLE
markers. Checks that the template-owned code is byte-for-byte the template's,
that the client pin is present, and that agent-editable code does not prompt,
read credentials, hard-code tokens or URLs, manage its own concurrency or
exits, swallow exceptions, write over raw HTTP, or load whole files. As a hook
it reports problems back to Claude with a `block` decision; on anything else
it stays silent.
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _hooklib import (  # noqa: E402
    CLIENT_PIN,
    TEMPLATE,
    emit,
    hardcoded_tokens,
    header,
    is_registration_script,
    read_input,
    split_regions,
)

# (pattern, rule) checked line by line in the AGENT-EDITABLE region
AGENT_RULES = [
    (
        re.compile(r"\binput\s*\(|\bgetpass\b"),
        "no interactive prompts: pipelines run unattended",
    ),
    (
        re.compile(r"(os\.environ|os\.getenv|environ\.get)\b.*TOKEN"),
        "credentials are read by the template's catalog_connection(), not by agent code",
    ),
    (
        re.compile(r"\bCatalogClient\s*\("),
        "the template owns the client (retry policy, compatibility check)",
    ),
    (
        re.compile(r"https?://[^\s\"']*czi\.team|-sci-data\.|CATALOG_API_URL"),
        "the catalog URL comes from CATALOG_API_URL via the template; do not hard-code or read it",
    ),
    (
        re.compile(
            r"ThreadPoolExecutor|ProcessPoolExecutor|multiprocessing|asyncio\.gather"
        ),
        "concurrency belongs to run_batch (bounded, per-record isolation)",
    ),
    (
        re.compile(r"\b(sys\.exit|exit|quit)\s*\("),
        "do not exit from agent code; raise and let run_batch record the failure",
    ),
    (
        re.compile(
            r"\b(requests|httpx|urllib\.request)\.\w+\(.*\b(post|put|patch|delete)\b|\.(post|put|patch|delete)\s*\("
        ),
        "write through the template's client.register(); raw HTTP writes skip the dry run and the upsert",
    ),
    (
        re.compile(r"\.read_bytes\(\s*\)|\.read\(\s*\)"),
        "stream files (catalog_client.utils.checksum); never load a whole file",
    ),
]
SWALLOW_RE = re.compile(
    r"^\s*except\b[^\n]*:\s*(#[^\n]*)?\n\s*(pass|continue)\b", re.MULTILINE
)
REGISTER_CALL_RE = re.compile(r"\.(register|submit)\s*\(")
BARE_EXCEPT_RE = re.compile(r"^\s*except\s*:", re.MULTILINE)


def lint_text(text: str, path: str = "<script>") -> list[str]:
    if not is_registration_script(text):
        return []
    problems = []
    try:
        compile(text, path, "exec")
    except SyntaxError as exc:
        problems.append(f"line {exc.lineno}: syntax error: {exc.msg}")
    regions = split_regions(text)
    if regions is None:
        return problems + [
            "the TEMPLATE-OWNED / AGENT-EDITABLE / END AGENT-EDITABLE markers are missing or out of order; "
            f"start again from {TEMPLATE}"
        ]
    head, editable, tail = regions
    expected = split_regions(TEMPLATE.read_text())
    assert expected is not None
    for name, actual, wanted in (
        ("TEMPLATE-OWNED", head, expected[0]),
        ("template tail", tail, expected[2]),
    ):
        if actual != wanted:
            diff = list(
                difflib.unified_diff(
                    wanted.splitlines(), actual.splitlines(), lineterm="", n=0
                )
            )[2:6]
            problems.append(
                f"{name} section differs from {TEMPLATE.name}; restore it and move the change into an "
                f"AGENT-EDITABLE function or mapping.json. First difference: {' | '.join(diff)}"
            )
    if CLIENT_PIN not in header(text):
        problems.append(
            f"the script header must pin {CLIENT_PIN!r} in its PEP 723 dependencies"
        )
    offset = text[: text.find(editable)].count("\n")
    for number, line in enumerate(editable.splitlines(), start=offset + 1):
        code = line.split("#", 1)[0]
        for pattern, rule in AGENT_RULES:
            if pattern.search(code):
                problems.append(f"line {number}: {rule}")
    for number, line in enumerate(editable.splitlines(), start=offset + 1):
        call = REGISTER_CALL_RE.search(line.split("#", 1)[0])
        if call and not (
            "update_if_exists=True" in line and "error_on_duplicate=False" in line
        ):
            problems.append(
                f"line {number}: {call.group(1)}() must pass update_if_exists=True, error_on_duplicate=False "
                "or a second run raises DuplicateDatasetError (registration belongs in the template anyway)"
            )
    for match in list(SWALLOW_RE.finditer(editable)) + list(
        BARE_EXCEPT_RE.finditer(editable)
    ):
        number = offset + editable.count("\n", 0, match.start()) + 1
        problems.append(
            f"line {number}: do not swallow exceptions; a failed record must reach the batch summary"
        )
    problems += hardcoded_tokens(text)
    return problems


def lint_mapping(path: Path) -> list[str]:
    try:
        json.loads(path.read_text())
    except ValueError as exc:
        return [f"{path.name} is not valid JSON: {exc}"]
    except OSError:
        return []
    return []


def problems_for(path: Path) -> list[str]:
    try:
        if path.suffix == ".py":
            return lint_text(path.read_text(errors="replace"), str(path))
        if path.name == "mapping.json":
            siblings = [
                p
                for p in path.parent.glob("*.py")
                if is_registration_script(p.read_text(errors="replace"))
            ]
            return lint_mapping(path) if siblings else []
    except OSError:
        return []
    return []


def main(argv: list[str]) -> int:
    if argv:
        found = problems_for(Path(argv[0]))
        print("\n".join(found) if found else "ok")
        return 1 if found else 0
    data = read_input()
    if not data:
        return 0
    file_path = (data.get("tool_input") or {}).get("file_path")
    if not isinstance(file_path, str):
        return 0
    found = problems_for(Path(file_path))
    if found:
        emit(
            {
                "decision": "block",
                "reason": f"Registration script lint failed for {file_path} (pipeline-safety rules, "
                "registration-script skill):\n- " + "\n- ".join(found),
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
