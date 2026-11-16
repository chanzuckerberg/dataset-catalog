#!/usr/bin/env python3
"""Rebuild fields.json from the client models and the live API spec.

    python3 generate_fields.py                    # client models + live spec from CATALOG_API_URL
    python3 generate_fields.py --spec spec.json   # use a saved OpenAPI document instead
    python3 generate_fields.py --no-client        # spec only (fields then read as API-only)

Writes skills/registration-script/fields.json. Stdlib only: the client models are
read through ``model_json_schema()`` when ``catalog_client`` is importable from
this interpreter. Run it at plugin release and commit the output.

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

FIELDS_JSON = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "registration-script"
    / "fields.json"
)
SPEC_PATHS = ("/api/v1/meta/openapi.json", "/api/meta/openapi.json")
API_PREFIX = "/api/v1/"

# model key -> request model the catalog accepts for it
MODELS = {
    "dataset": "DatasetRequest",
    "asset": "DataAssetRequest",
    "collection": "CollectionRequest",
    "lineage": "LineageEdgeRequest",
}
# A nested model that is also a top-level model; others reference it instead of
# repeating its fields.
SPLIT_MODELS = {v: k for k, v in MODELS.items()}


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


# ---------------------------------------------------------------------- main


def build(client: dict, spec: dict | None, stamp: dict) -> dict:
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
    return {"stamp": stamp, "models": models}


def write(doc: dict, out: Path) -> None:
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


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
    parser.add_argument("--out", type=Path, default=FIELDS_JSON)
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
        stamp = {
            "generated": args.date,
            "client_version": client_version,
            "record_schema_version": record_version,
            "api_source": source,
            "api_version": spec.get("info", {}).get("version"),
        }
        doc = build(client, spec, stamp)
    except (GenerateError, OSError, ValueError) as exc:
        print(f"generate: {exc}", file=sys.stderr)
        return 1
    write(doc, args.out)
    counts = {
        m: sum(1 for f in d["fields"].values() if f["source"] != "both")
        for m, d in doc["models"].items()
    }
    print(
        f"generate: wrote {args.out} (client {client_version}); drift by model: {counts}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
