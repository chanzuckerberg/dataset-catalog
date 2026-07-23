#!/usr/bin/env python3
"""PreToolUse hook: auto-approve read-only Scientific Dataset Catalog commands.

Enabled with the `catalog` plugin. Emits an "allow" decision only for
unambiguous catalog GET/read commands (the shared `preflight.py`, the `catalog`
CLI reads, the bundled `search_expanded.py` / `ols.py`, and the stdlib `urllib`
REST GETs used by the catalog-read / catalog-search skills). For everything else — including the
register script and any HTTP mutation — it stays silent and defers to Claude's
normal permission flow. A hook "allow" never overrides a user's explicit
deny/ask rule.
"""

import json
import re
import sys

try:
    data = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    sys.exit(0)  # malformed input: defer, never crash the tool call

cmd = data.get("tool_input", {}).get("command", "")

# Never auto-approve a write: the register script, or an inline HTTP call that
# carries a body / non-GET method.
mutates = (
    "register_dataset.py" in cmd
    or re.search(r'method\s*=\s*["\'](POST|PUT|PATCH|DELETE)', cmd)
    or re.search(r"\bdata\s*=", cmd)
)

reads = (
    re.search(r"\bcatalog\s+(search|get|list|facets|lineage|collections)\b", cmd)
    or re.search(r"\bcatalog\s+--version\b", cmd)
    or "preflight.py" in cmd
    or "search_expanded.py" in cmd
    or "ols.py" in cmd
    # stdlib REST GET against the catalog: token/host present, no mutation
    or ("urlopen" in cmd and ("X-catalog-api-token" in cmd or "CATALOG_API" in cmd))
)

if reads and not mutates:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": "catalog and ols read-only query auto-approved by catalog plugin",
                }
            }
        )
    )

sys.exit(0)  # silence = defer to Claude's normal permission flow
