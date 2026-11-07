#!/usr/bin/env python3
"""Rebuild the field reference from the client models, the live API spec, and examples.json.

    python3 generate.py                      # client models + live spec from CATALOG_API_URL
    python3 generate.py --spec spec.json     # use a saved OpenAPI document instead
    python3 generate.py --no-client          # spec only (fields then read as API-only)

Writes ../fields/{dataset,asset,collection,lineage}.md and ../fields.json. Stdlib
only: the client models are read through ``model_json_schema()`` when
``catalog_client`` is importable from this interpreter. Run it at plugin release
and commit the output; examples.json is the only hand-edited input.

The spec is fetched with the token sent as the X-catalog-api-token header, read
from CATALOG_API_TOKEN; it is never printed.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SPEC_PATHS = ("/api/v1/meta/openapi.json", "/api/meta/openapi.json")
API_PREFIX = "/api/v1/"

# model file -> request model the catalog accepts for it
MODELS = {
    "dataset": "DatasetRequest",
    "asset": "DataAssetRequest",
    "collection": "CollectionRequest",
    "lineage": "LineageEdgeRequest",
}
# A nested model documented in its own file; other models link to it instead of
# repeating its fields.
SPLIT_MODELS = {v: k for k, v in MODELS.items()}
TITLES = {
    "dataset": "Dataset",
    "asset": "Asset (location)",
    "collection": "Collection",
    "lineage": "Lineage edge",
}


class GenerateError(Exception):
    pass


# ------------------------------------------------------------------ sources


def client_schemas() -> tuple[dict, str | None, str | None]:
    """Return ({model: json_schema}, client_version, record_schema_version)."""
    try:
        from catalog_client.models.asset import DataAssetRequest
        from catalog_client.models.collection import CollectionRequest
        from catalog_client.models.dataset import DatasetRequest
        from catalog_client.models.lineage import LineageEdgeRequest
    except ImportError:
        return {}, None, None
    import importlib.metadata

    try:
        version = importlib.metadata.version("catalog-client")
    except importlib.metadata.PackageNotFoundError:
        version = None
    classes = {
        "DatasetRequest": DatasetRequest,
        "DataAssetRequest": DataAssetRequest,
        "CollectionRequest": CollectionRequest,
        "LineageEdgeRequest": LineageEdgeRequest,
    }
    schemas = {name: cls.model_json_schema() for name, cls in classes.items()}
    record_version = DatasetRequest.model_fields["record_schema_version"].default
    return schemas, version, record_version


def fetch_spec(base_url: str, token: str) -> tuple[dict, str]:
    errors = []
    for path in SPEC_PATHS:
        request = urllib.request.Request(
            base_url.rstrip("/") + path,
            headers={"X-catalog-api-token": token, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                spec = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            errors.append(f"{path}: HTTP {exc.code}")
            continue
        except urllib.error.URLError as exc:
            errors.append(f"{path}: {exc.reason}")
            continue
        except ValueError:
            errors.append(f"{path}: non-JSON response (SSO redirect?)")
            continue
        if isinstance(spec, dict) and "paths" in spec:
            return spec, base_url.rstrip("/") + path
        errors.append(f"{path}: JSON but not an OpenAPI document")
    raise GenerateError("could not fetch the API spec: " + "; ".join(errors))


def reachable_schemas(spec: dict) -> set[str]:
    """Schema names referenced (transitively) from /api/v1/ paths.

    The spec also lists UI-only schemas that no API path uses; those are not
    part of the record contract.
    """
    schemas = spec.get("components", {}).get("schemas", {})
    seen: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                if name not in seen:
                    seen.add(name)
                    walk(schemas.get(name, {}))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(
        {p: ops for p, ops in spec.get("paths", {}).items() if p.startswith(API_PREFIX)}
    )
    return seen


# ---------------------------------------------------------------- flattening


def _ref_name(node: dict) -> str | None:
    ref = node.get("$ref")
    return ref.rsplit("/", 1)[-1] if isinstance(ref, str) else None


def describe(node: dict, defs: dict) -> dict:
    """Normalize one JSON-schema property into a flat type description."""
    branches = node.get("anyOf") or node.get("oneOf") or [node]
    out: dict = {
        "types": [],
        "enum": None,
        "enum_name": None,
        "model": None,
        "items": None,
    }
    for branch in branches:
        name = _ref_name(branch)
        target = defs.get(name, {}) if name else branch
        if name and "enum" in target:
            out["types"].append(target.get("type", "string"))
            out["enum"] = list(target["enum"])
            out["enum_name"] = name
            continue
        if "enum" in target:
            out["types"].append(target.get("type", "string"))
            out["enum"] = list(target["enum"])
            continue
        if name and "properties" in target:
            out["types"].append("object")
            out["model"] = name
            continue
        kind = target.get("type")
        if kind == "array":
            out["types"].append("array")
            out["items"] = describe(target.get("items", {}), defs)
            if "minItems" in target:
                out["min_items"] = target["minItems"]
        elif kind:
            out["types"].append(kind)
            if "format" in target:
                out["format"] = target["format"]
        else:
            out["types"].append("any")
    out["types"] = list(dict.fromkeys(out["types"]))
    return out


def type_label(desc: dict) -> str:
    parts = []
    for kind in desc["types"]:
        if kind == "null":
            continue
        if kind == "array" and desc.get("items"):
            parts.append(f"list of {type_label(desc['items'])}")
        elif kind == "object" and desc.get("model"):
            parts.append(desc["model"])
        elif desc.get("enum") and kind == "string":
            parts.append(
                "enum "
                + (desc.get("enum_name") or "")
                + " — "
                + " | ".join(f"`{v}`" for v in desc["enum"])
            )
        elif desc.get("format"):
            parts.append(f"{kind} ({desc['format']})")
        else:
            parts.append(kind)
    label = " or ".join(parts) or "any"
    return label + (", nullable" if "null" in desc["types"] else "")


def flatten(root: str, defs: dict) -> dict:
    """Map dotted field paths (arrays as ``[]``) to field records for one model."""
    fields: dict = {}

    def visit(model_name: str, prefix: str, stack: tuple):
        model = defs.get(model_name, {})
        required = set(model.get("required", []))
        for name, prop in model.get("properties", {}).items():
            path = f"{prefix}{name}"
            desc = describe(prop, defs)
            record = {
                "type": type_label(desc),
                "json_types": desc["types"],
                "required": name in required,
                "description": prop.get("description", ""),
            }
            if "default" in prop:
                record["default"] = prop["default"]
            if desc.get("enum"):
                record["enum"] = desc["enum"]
            if desc.get("format"):
                record["format"] = desc["format"]
            if desc.get("min_items") is not None:
                record["min_items"] = desc["min_items"]
            fields[path] = record
            nested = desc.get("model")
            item = desc.get("items") or {}
            if item.get("enum"):
                record["item_enum"] = item["enum"]
            if item.get("types"):
                record["item_types"] = item["types"]
            for child, child_prefix in (
                (nested, f"{path}."),
                (item.get("model"), f"{path}[]."),
            ):
                if not child:
                    continue
                if child in SPLIT_MODELS and child != root:
                    key = "model_ref" if child == nested else "items_model"
                    record[key] = SPLIT_MODELS[child]
                    continue
                if child in stack:
                    continue
                record["object" if child == nested else "items_object"] = child
                record[
                    "extra_allowed" if child == nested else "items_extra_allowed"
                ] = bool(defs.get(child, {}).get("additionalProperties"))
                visit(child, child_prefix, stack + (child,))

    visit(root, "", (root,))
    return fields


def defs_for(schema: dict, root: str) -> dict:
    """Client schema: $defs plus the root model itself, keyed by name."""
    defs = dict(schema.get("$defs", {}))
    defs[root] = {k: v for k, v in schema.items() if k != "$defs"}
    return defs


# ------------------------------------------------------------------- merging


def merge(client: dict, api: dict) -> dict:
    merged = {}
    for path in list(client) + [p for p in api if p not in client]:
        c, a = client.get(path), api.get(path)
        record = dict(c or a or {})
        record["source"] = "both" if c and a else ("client-only" if c else "api-only")
        if c and a:
            if c.get("enum") != a.get("enum") and a.get("enum"):
                record["api_enum"] = a["enum"]
            if c["required"] != a["required"]:
                record["api_required"] = a["required"]
            if not record.get("description"):
                record["description"] = a.get("description", "")
        merged[path] = record
    return merged


def apply_curated(models: dict, curated: dict) -> list[str]:
    """Attach examples.json entries; return keys that no longer match a field."""
    stale = []
    for model, entries in curated.get("fields", {}).items():
        fields = models.get(model, {}).get("fields")
        if fields is None:
            stale.append(model)
            continue
        for path, extra in entries.items():
            if path not in fields:
                stale.append(f"{model}:{path}")
                continue
            for key in ("meaning", "decided_by", "common_mistakes", "examples"):
                if key in extra:
                    fields[path][key] = extra[key]
    return stale


# ------------------------------------------------------------------ markdown


def _value(value) -> str:
    return "`" + json.dumps(value, ensure_ascii=False) + "`"


def _parent(path: str) -> str:
    head, _, _ = path.rpartition(".")
    return head


def render_model(name: str, fields: dict, stamp: dict) -> str:
    lines = [
        f"# {TITLES[name]} fields (`{MODELS[name]}`)",
        "",
        "<!-- Generated by scripts/generate.py. Do not edit: change examples.json and regenerate. -->",
        "",
        f"Generated {stamp['generated']} from catalog-client {stamp['client_version'] or 'not installed'}"
        f" (record_schema_version {stamp['record_schema_version'] or 'unknown'}) and the API spec at"
        f" `{stamp['api_source'] or 'none'}`.",
        "",
        "Source: **both** = client and API agree on the field; **API-only** = the API accepts it but the"
        " installed client has no field for it yet (send it over REST); **client-only** = the client"
        " models it but the API spec does not list it.",
        "",
    ]
    groups: dict[str, list[str]] = {}
    for path in fields:
        groups.setdefault(_parent(path), []).append(path)
    for group, paths in groups.items():
        lines += [f"## {group or 'Top level'}", ""]
        for path in paths:
            f = fields[path]
            lines.append(f"### {path}")
            lines.append(f"- Type: {f['type']}")
            required = "yes" if f["required"] else "no"
            if group:
                required += f" (when `{group}` is present)"
            if "api_required" in f:
                required += (
                    f"; API says {'required' if f['api_required'] else 'optional'}"
                )
            lines.append(f"- Required: {required}")
            if f.get("min_items"):
                lines.append(f"- Minimum items: {f['min_items']}")
            if "default" in f and f["default"] is not None:
                lines.append(f"- Default: {_value(f['default'])}")
            if f.get("item_enum"):
                lines.append(
                    "- Allowed values: " + " | ".join(f"`{v}`" for v in f["item_enum"])
                )
            if f.get("api_enum"):
                lines.append(
                    "- API allows: " + " | ".join(f"`{v}`" for v in f["api_enum"])
                )
            if f.get("model_ref") or f.get("items_model"):
                ref = f.get("model_ref") or f.get("items_model")
                lines.append(f"- Fields: see [{ref}.md]({ref}.md)")
            if f.get("extra_allowed") or f.get("items_extra_allowed"):
                lines.append(
                    "- Extra keys: accepted and stored (a typo'd field name is kept, not rejected)"
                )
            source = {
                "both": "client + API",
                "api-only": "**API-only**",
                "client-only": "**client-only**",
            }
            lines.append(f"- Source: {source[f['source']]}")
            meaning = f.get("meaning") or f.get("description")
            if meaning:
                lines.append(f"- Meaning: {meaning}")
            if f.get("decided_by"):
                lines.append(f"- Decided by: {f['decided_by']}")
            if f.get("examples"):
                lines.append("- Examples:")
                for ex in f["examples"]:
                    note = f" — {ex['note']}" if ex.get("note") else ""
                    lines.append(
                        f"  - {ex['data_type'].capitalize()}: {_value(ex['value'])}{note}"
                    )
            if f.get("common_mistakes"):
                lines.append(f"- Common mistakes: {f['common_mistakes']}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------- main


def build(client: dict, spec: dict | None, curated: dict, stamp: dict) -> dict:
    api_defs = spec.get("components", {}).get("schemas", {}) if spec else {}
    reachable = reachable_schemas(spec) if spec else set()
    models = {}
    for name, root in MODELS.items():
        client_fields = (
            flatten(root, defs_for(client[root], root)) if root in client else {}
        )
        api_fields = flatten(root, api_defs) if root in reachable else {}
        if not client_fields and not api_fields:
            raise GenerateError(
                f"{root} is in neither the client models nor the /api/v1/ spec"
            )
        root_def = (
            defs_for(client[root], root)[root]
            if root in client
            else api_defs.get(root, {})
        )
        models[name] = {
            "root": root,
            "extra_allowed": bool(root_def.get("additionalProperties")),
            "fields": merge(client_fields, api_fields),
        }
    stale = apply_curated(models, curated)
    if stale:
        raise GenerateError(
            "examples.json names fields that no longer exist: " + ", ".join(stale)
        )
    return {"stamp": stamp, "models": models}


def write(doc: dict, out_dir: Path) -> None:
    (out_dir / "fields").mkdir(parents=True, exist_ok=True)
    for name, model in doc["models"].items():
        (out_dir / "fields" / f"{name}.md").write_text(
            render_model(name, model["fields"], doc["stamp"])
        )
    (out_dir / "fields.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--spec", help="path to a saved OpenAPI JSON document (default: fetch live)"
    )
    parser.add_argument(
        "--url",
        help="catalog base URL for the live spec (default: CATALOG_API_URL)",
    )
    parser.add_argument(
        "--no-client", action="store_true", help="ignore an installed catalog_client"
    )
    parser.add_argument("--examples", type=Path, default=SKILL_DIR / "examples.json")
    parser.add_argument("--out", type=Path, default=SKILL_DIR)
    parser.add_argument(
        "--date", default=datetime.date.today().isoformat(), help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)

    try:
        client, client_version, record_version = (
            ({}, None, None) if args.no_client else client_schemas()
        )
        if not client and not args.no_client:
            raise GenerateError(
                "catalog_client is not importable from this interpreter; run with the client's Python, "
                "or pass --no-client to build from the API spec alone"
            )
        if args.spec:
            spec, source = json.loads(Path(args.spec).read_text()), Path(args.spec).name
        else:
            url = args.url or os.environ.get("CATALOG_API_URL")
            token = os.environ.get("CATALOG_API_TOKEN")
            if not url or not token:
                raise GenerateError(
                    "set CATALOG_API_URL and CATALOG_API_TOKEN (or pass --url), or pass --spec FILE "
                    "to work offline"
                )
            spec, source = fetch_spec(url, token)
        curated = (
            json.loads(args.examples.read_text()) if args.examples.exists() else {}
        )
        stamp = {
            "generated": args.date,
            "client_version": client_version,
            "record_schema_version": record_version,
            "api_source": source,
            "api_version": spec.get("info", {}).get("version"),
        }
        doc = build(client, spec, curated, stamp)
    except (GenerateError, OSError, ValueError) as exc:
        print(f"generate: {exc}", file=sys.stderr)
        return 1
    write(doc, args.out)
    counts = {
        m: sum(1 for f in d["fields"].values() if f["source"] != "both")
        for m, d in doc["models"].items()
    }
    print(
        f"generate: wrote {args.out}/fields.json and fields/*.md (client {client_version}); drift by model: {counts}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
