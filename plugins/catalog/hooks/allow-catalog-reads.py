#!/usr/bin/env python3
"""PreToolUse hook: auto-approve read-only Scientific Dataset Catalog commands.

Enabled with the `catalog` plugin. Emits an "allow" decision only for
unambiguous catalog GET/read commands (the shared `preflight.py`, the `catalog`
CLI reads, the bundled `search_expanded.py` / `ols.py`, and the stdlib `urllib`
REST GETs that send the token as the `X-catalog-api-token` header to a catalog
host). For everything else — including the register script, any HTTP mutation,
and any request to a non-catalog host — it stays silent and defers to Claude's
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
# carries a body / non-GET method. A body is bytes, so `urlopen(url, b"…")` /
# `Request(url, data)` positional bodies show up as a bytes literal or an
# `.encode(` — reads never build one, so treat any of these as a mutation.
# (A body assembled across statements would need `;`, already deferred above.)
mutates = (
    "register_dataset.py" in cmd
    or re.search(r'method\s*=\s*["\'](POST|PUT|PATCH|DELETE)', cmd)
    or re.search(r"\bdata\s*=", cmd)
    or re.search(r"\bb['\"]", cmd)
    or ".encode(" in cmd
)

# Hosts the catalog reads target: datacatalog.<env>-sci-data.<env>.czi.team,
# where <env> is dev, staging, or prod. A URL literal to any OTHER host is a
# red flag — a token can only be exfiltrated by shipping it elsewhere, and this
# substring hook can't vouch for that. The legit stdlib read builds its URL from
# CATALOG_API_URL / a catalog host, so it carries no foreign literal.
CATALOG_HOST_RE = re.compile(
    r"datacatalog\.(dev|staging|prod)-sci-data\.(dev|staging|prod)\.czi\.team(:\d+)?",
    re.IGNORECASE,
)
# Every `http(s)://` scheme literal must be immediately followed by a catalog
# host. An empty capture (`http://` split from its host by concatenation, e.g.
# `'http://'+h`) fails the match too, so a dynamically assembled foreign URL is
# refused rather than waved through.
foreign_url = any(
    not CATALOG_HOST_RE.fullmatch(host)
    for host in re.findall(r"https?://([^\s'\"/]*)", cmd)
)

reads = (
    re.search(r"\bcatalog\s+(search|get|list|facets|lineage)\b", cmd)
    # collections is a resource with mutating subcommands; allow only its reads.
    or re.search(r"\bcatalog\s+collections\s+(list|get|entries|parents)\b", cmd)
    or re.search(r"\bcatalog\s+--version\b", cmd)
    # bundled read-only scripts, anchored to the scripts/ dir (not a bare filename).
    or re.search(r"scripts/(preflight|search_expanded|ols)\.py\b", cmd)
    # stdlib REST GET against the catalog. Require the sanctioned read signature:
    # the token sent as the X-catalog-api-token *header* (exfiltration puts it in
    # the URL instead), no mutation, and no URL literal to a non-catalog host.
    or ("urlopen" in cmd and "X-catalog-api-token" in cmd and not foreign_url)
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
