#!/usr/bin/env python3
"""Discover the live Catalog API surface from its OpenAPI spec.

The Catalog API is still in flux: paths, parameters, and response shapes can
change between deployments. This script is the drift-proof way to learn the
*current* surface — it fetches the live OpenAPI spec (probing the known spec
locations) and prints a distilled map, keeping the raw multi-thousand-line
spec out of the conversation.

    api_map.py                     # every operation: METHOD PATH — summary
    api_map.py datasets/search     # GET ops matching the substring: params +
                                   # response fields, with enums and defaults
    api_map.py lineage --json      # same, machine-readable

Read-only: issues only GET requests, token sent as the X-catalog-api-token
header (never on a command line). Config comes from CATALOG_API_URL /
CATALOG_API_TOKEN, same as every bundled script.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from _catalog import DEFAULT_TIMEOUT, EXIT_USAGE, _resolve_config

# Candidate spec locations, most likely first. A deployment may move the spec;
# probing them all means a relocation degrades to a slower first call, not a
# broken skill.
SPEC_PATHS = (
    "/api/meta/openapi.json",
    "/api/openapi.json",
    "/openapi.json",
)


def fetch_spec() -> tuple[dict, str]:
    """Return (spec, path) from the first candidate that yields an OpenAPI doc."""
    base_url, token = _resolve_config()
    base = base_url.rstrip("/")
    headers = {"X-catalog-api-token": token, "Accept": "application/json"}
    errors: list[str] = []
    for path in SPEC_PATHS:
        request = urllib.request.Request(f"{base}{path}", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            errors.append(f"{path}: HTTP {exc.code}")
            continue
        except urllib.error.URLError as exc:
            errors.append(f"{path}: {exc.reason}")
            continue
        try:
            spec = json.loads(body)
        except json.JSONDecodeError:
            # An SSO login page comes back as HTML; treat it like a miss.
            errors.append(f"{path}: non-JSON response (SSO redirect?)")
            continue
        if isinstance(spec, dict) and "paths" in spec:
            return spec, path
        errors.append(f"{path}: JSON but not an OpenAPI document")
    print(
        "error: could not fetch the OpenAPI spec from any known location:",
        file=sys.stderr,
    )
    for line in errors:
        print(f"  {line}", file=sys.stderr)
    print(
        "Check CATALOG_API_URL / CATALOG_API_TOKEN (run scripts/preflight.py).",
        file=sys.stderr,
    )
    raise SystemExit(EXIT_USAGE)


def _deref(spec: dict, node: dict) -> dict:
    """Follow a $ref (one hop is enough for this spec's schemas)."""
    ref = node.get("$ref")
    if not ref:
        return node
    target: dict = spec
    for part in ref.lstrip("#/").split("/"):
        target = target.get(part, {})
    return target


def _schema_fields(spec: dict, schema: dict) -> dict[str, str]:
    """Flatten a response schema to {field: type}, unwrapping arrays and refs."""
    schema = _deref(spec, schema)
    if schema.get("type") == "array":
        schema = _deref(spec, schema.get("items", {}))
    fields = {}
    for name, prop in (schema.get("properties") or {}).items():
        prop = _deref(spec, prop)
        kind = prop.get("type") or ("ref" if "$ref" in prop else "any")
        if kind == "array":
            item = _deref(spec, prop.get("items", {}))
            kind = f"array[{item.get('type') or item.get('title') or 'object'}]"
        fields[name] = kind
    return fields


def _operation_map(spec: dict, pattern: str | None) -> list[dict]:
    """Distill matching operations into plain dicts."""
    ops = []
    for path in sorted(spec.get("paths", {})):
        if pattern and pattern not in path:
            continue
        for method, op in spec["paths"][path].items():
            if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                continue
            entry: dict = {
                "method": method.upper(),
                "path": path,
                "summary": op.get("summary")
                or op.get("description", "").split("\n")[0],
            }
            if pattern:  # detail mode: include params + response fields
                entry["parameters"] = [
                    {
                        "name": p["name"],
                        "in": p.get("in", "query"),
                        "required": bool(p.get("required")),
                        "type": _deref(spec, p.get("schema", {})).get("type"),
                        "default": _deref(spec, p.get("schema", {})).get("default"),
                        "enum": _deref(spec, p.get("schema", {})).get("enum"),
                        "description": (p.get("description") or "")[:300],
                    }
                    for p in op.get("parameters", [])
                ]
                content = (
                    op.get("responses", {})
                    .get("200", {})
                    .get("content", {})
                    .get("application/json", {})
                )
                if content.get("schema"):
                    entry["response_fields"] = _schema_fields(spec, content["schema"])
            ops.append(entry)
    return ops


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "pattern", nargs="?", help="substring of a path; shows params + response fields"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit the distilled map as JSON",
    )
    args = parser.parse_args(argv)

    spec, spec_path = fetch_spec()
    ops = _operation_map(spec, args.pattern)
    if not ops:
        print(
            f"no operations match {args.pattern!r} (spec at {spec_path})",
            file=sys.stderr,
        )
        return 1

    if args.as_json:
        print(json.dumps({"spec_path": spec_path, "operations": ops}, indent=2))
        return 0

    print(f"spec: {spec_path}")
    for op in ops:
        print(f"{op['method']:6} {op['path']}  {op['summary']}".rstrip())
        for p in op.get("parameters", []):
            req = "*" if p["required"] else " "
            line = f"    {req} {p['name']} ({p['type']}"
            if p["default"] is not None:
                line += f", default={p['default']}"
            line += ")"
            if p["enum"]:
                line += f" one of: {', '.join(map(str, p['enum']))}"
            elif p["description"]:
                line += f"  {p['description'].splitlines()[0]}"
            print(line)
        fields = op.get("response_fields")
        if fields:
            listed = ", ".join(f"{k}:{v}" for k, v in fields.items())
            print(f"      200 -> {listed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
