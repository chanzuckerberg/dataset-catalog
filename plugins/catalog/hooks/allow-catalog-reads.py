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

# Defer anything with shell chaining, piping, redirection, a newline, or command
# substitution: a substring match on the first command can't vouch for a second
# one smuggled in after `;`, `&&`, `|`, `>`, or `$(...)`.
if re.search(r"[;&|<>`\n]|\$\(", cmd):
    sys.exit(0)

# Never auto-approve a write: the register script, or an inline HTTP call that
# carries a body / non-GET method.
mutates = (
    "register_dataset.py" in cmd
    or re.search(r'method\s*=\s*["\'](POST|PUT|PATCH|DELETE)', cmd)
    or re.search(r"\bdata\s*=", cmd)
)

reads = (
    re.search(r"\bcatalog\s+(search|get|list|facets|lineage)\b", cmd)
    # collections is a resource with mutating subcommands; allow only its reads.
    or re.search(r"\bcatalog\s+collections\s+(list|get)\b", cmd)
    or re.search(r"\bcatalog\s+--version\b", cmd)
    # bundled read-only scripts, anchored to the scripts/ dir (not a bare filename).
    or re.search(r"scripts/(preflight|search_expanded|ols)\.py\b", cmd)
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
