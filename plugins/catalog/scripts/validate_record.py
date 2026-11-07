#!/usr/bin/env python3
"""Validate a draft catalog record (JSON) before registration.

    validate_record.py PATH|-  [--model dataset|asset|collection|lineage]

Checks the record against skills/field-reference/fields.json: required fields,
types, allowed values, list minimums, and keys the schema does not have (which
the API would silently drop). For dataset records, when the `catalog` CLI is
installed, also runs `catalog validate` for the client's full pydantic
validation and merges its findings.

Output matches `catalog validate`: `valid`, or one `<dotted.path>: <message>`
line per problem. Exit 0 = valid, 1 = invalid, 2 = unreadable input.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

FIELDS_JSON = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "field-reference"
    / "fields.json"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TYPE_NAMES = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "list",
    "object": "dictionary",
}


def kind_of(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null"


def _choices(values: list) -> str:
    quoted = [f"'{v}'" for v in values]
    return (
        quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " or " + quoted[-1]
    )


class Validator:
    def __init__(self, doc: dict):
        self.models = doc["models"]
        self.children: dict[str, dict[str, dict[str, dict]]] = {}
        for model, data in self.models.items():
            index: dict[str, dict[str, dict]] = {}
            for path, spec in data["fields"].items():
                parent, _, name = path.rpartition(".")
                index.setdefault(parent, {})[name] = spec
            self.children[model] = index
        self.errors: list[str] = []

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"{path or '<root>'}: {message}")

    def record(self, value: object, model: str, display: str = "") -> None:
        self.check_object(
            value, model, "", display, self.models[model].get("extra_allowed", False)
        )

    def check_object(
        self, value: object, model: str, schema_path: str, display: str, extra: bool
    ) -> None:
        if not isinstance(value, dict):
            self.error(display, "Input should be a valid dictionary")
            return
        known = self.children[model].get(schema_path, {})
        for name, spec in known.items():
            child_display = f"{display}.{name}" if display else name
            child_schema = f"{schema_path}.{name}" if schema_path else name
            if name not in value:
                if spec["required"]:
                    self.error(child_display, "Field required")
                continue
            self.check_value(value[name], spec, model, child_schema, child_display)
        if not extra:
            for name in value:
                if name not in known:
                    child_display = f"{display}.{name}" if display else name
                    self.error(
                        child_display,
                        "Extra inputs are not permitted (not in the schema; the API would drop it)",
                    )

    def check_value(
        self, value: object, spec: dict, model: str, schema_path: str, display: str
    ) -> None:
        types = spec.get("json_types") or ["any"]
        kind = kind_of(value)
        if "any" in types:
            return
        if kind == "null":
            if "null" not in types:
                expected = next((t for t in types if t != "null"), "value")
                self.error(
                    display,
                    f"Input should be a valid {TYPE_NAMES.get(expected, expected)}",
                )
            return
        if kind not in types and not (kind == "integer" and "number" in types):
            expected = next((t for t in types if t != "null"), "value")
            self.error(
                display, f"Input should be a valid {TYPE_NAMES.get(expected, expected)}"
            )
            return
        if kind == "string":
            if spec.get("enum") and value not in spec["enum"]:
                self.error(display, f"Input should be {_choices(spec['enum'])}")
            if spec.get("format") == "date" and not DATE_RE.match(str(value)):
                self.error(
                    display, "Input should be a valid date in the format YYYY-MM-DD"
                )
        elif kind == "array":
            assert isinstance(value, list)
            minimum = spec.get("min_items")
            if minimum and len(value) < minimum:
                self.error(
                    display,
                    f"List should have at least {minimum} item after validation, not {len(value)}",
                )
            for index, item in enumerate(value):
                item_display = f"{display}.{index}"
                if spec.get("items_model"):
                    self.record(item, spec["items_model"], item_display)
                elif spec.get("items_object"):
                    self.check_object(
                        item,
                        model,
                        f"{schema_path}[]",
                        item_display,
                        spec.get("items_extra_allowed", False),
                    )
                else:
                    item_spec = {
                        "json_types": spec.get("item_types") or ["any"],
                        "enum": spec.get("item_enum"),
                    }
                    self.check_value(
                        item, item_spec, model, f"{schema_path}[]", item_display
                    )
        elif kind == "object":
            if spec.get("model_ref"):
                self.record(value, spec["model_ref"], display)
            elif spec.get("object"):
                self.check_object(
                    value, model, schema_path, display, spec.get("extra_allowed", False)
                )


def stdlib_errors(record: object, model: str, doc: dict) -> list[str]:
    validator = Validator(doc)
    validator.record(record, model)
    return validator.errors


def cli_errors(text: str) -> list[str] | None:
    """Run `catalog validate -` when available; None when it can't (absent or too old)."""
    cli = shutil.which("catalog")
    if not cli:
        return None
    try:
        result = subprocess.run(
            [cli, "validate", "-"],
            input=text,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode not in (0, 1):
        return None
    return [
        line
        for line in result.stdout.splitlines()
        if line.strip() and line.strip() != "valid"
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a draft catalog record.")
    parser.add_argument("path", help="JSON record file, or - for stdin")
    parser.add_argument(
        "--model",
        default="dataset",
        choices=["dataset", "asset", "collection", "lineage"],
    )
    parser.add_argument(
        "--fields", type=Path, default=FIELDS_JSON, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--no-cli",
        action="store_true",
        help="skip `catalog validate` even if installed",
    )
    args = parser.parse_args(argv)

    try:
        text = sys.stdin.read() if args.path == "-" else Path(args.path).read_text()
    except OSError as exc:
        print(f"error: {args.path}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    try:
        record = json.loads(text)
    except ValueError as exc:
        print(
            f"error: {args.path}: not valid JSON ({exc}); YAML records are not supported",
            file=sys.stderr,
        )
        return 2
    try:
        doc = json.loads(args.fields.read_text())
    except (OSError, ValueError) as exc:
        print(
            f"error: cannot read field reference {args.fields}: {exc}", file=sys.stderr
        )
        return 2

    errors = stdlib_errors(record, args.model, doc)
    if args.model == "dataset" and not args.no_cli:
        errors += cli_errors(text) or []
    errors = list(dict.fromkeys(errors))
    if errors:
        print("\n".join(errors))
        return 1
    print("valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
