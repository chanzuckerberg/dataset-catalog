import copy
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from _support import PLUGIN_ROOT

GENERATE = PLUGIN_ROOT / "scripts" / "generate_fields.py"
_spec = importlib.util.spec_from_file_location("generate_fields", GENERATE)
assert _spec and _spec.loader
generate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate)


def ref(name: str, root: str = "#/components/schemas/") -> dict:
    return {"$ref": root + name}


def nullable(kind: str) -> dict:
    return {"anyOf": [{"type": kind}, {"type": "null"}]}


def body(name: str) -> dict:
    return {"requestBody": {"content": {"application/json": {"schema": ref(name)}}}}


def models(root: str) -> dict:
    return {
        "DatasetModality": {"enum": ["imaging", "sequencing"], "type": "string"},
        "GovernanceMetadata": {
            "type": "object",
            "additionalProperties": True,
            "required": ["is_pii"],
            "properties": {
                "is_pii": {"type": "boolean", "description": "PII?"},
                "license": nullable("string"),
            },
        },
        "DataAssetRequest": {
            "type": "object",
            "required": ["location_uri"],
            "properties": {
                "location_uri": {"type": "string"},
                "size_bytes": nullable("integer"),
            },
        },
        "DatasetRequest": {
            "type": "object",
            "required": ["canonical_id", "modality", "governance", "locations"],
            "properties": {
                "canonical_id": {"type": "string", "description": "Stable id"},
                "modality": ref("DatasetModality", root),
                "governance": ref("GovernanceMetadata", root),
                "locations": {
                    "type": "array",
                    "items": ref("DataAssetRequest", root),
                    "minItems": 1,
                },
            },
        },
        "CollectionRequest": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        },
        "LineageEdgeRequest": {
            "type": "object",
            "required": ["source_dataset_id"],
            "properties": {"source_dataset_id": {"type": "string"}},
        },
    }


def fixture_spec() -> dict:
    schemas = models("#/components/schemas/")
    schemas["DatasetRequest"]["properties"]["api_field"] = {
        "type": "string",
        "description": "API ahead",
    }
    schemas["DatasetModality"]["enum"].append("text")
    schemas["SummaryResponse"] = {
        "type": "object",
        "properties": {"ui": {"type": "string"}},
    }
    return {
        "info": {"version": "0.1.0"},
        "paths": {
            "/api/v1/datasets/": {"post": body("DatasetRequest")},
            "/api/v1/collections/": {"post": body("CollectionRequest")},
            "/api/v1/lineage/": {"post": body("LineageEdgeRequest")},
            "/ui/summary": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {"schema": ref("SummaryResponse")}
                            }
                        }
                    }
                }
            },
        },
        "components": {"schemas": schemas},
    }


def fixture_client() -> dict:
    defs = models("#/$defs/")
    defs["DatasetRequest"]["properties"]["client_field"] = {"type": "string"}
    out = {}
    for root in (
        "DatasetRequest",
        "DataAssetRequest",
        "CollectionRequest",
        "LineageEdgeRequest",
    ):
        schema = copy.deepcopy(defs[root])
        schema["$defs"] = {k: v for k, v in defs.items() if k != root}
        out[root] = schema
    return out


STAMP = {
    "generated": "2026-01-01",
    "client_version": "9.9.9",
    "record_schema_version": "v1.7.0",
    "api_source": "fixture.json",
    "api_version": "0.1.0",
}


class GenerateTest(unittest.TestCase):
    def test_merge_marks_drift_and_shapes_fields(self):
        doc = generate.build(fixture_client(), fixture_spec(), STAMP)
        dataset = doc["models"]["dataset"]["fields"]
        self.assertEqual(dataset["canonical_id"]["source"], "both")
        self.assertTrue(dataset["canonical_id"]["required"])
        self.assertEqual(dataset["api_field"]["source"], "api-only")
        self.assertEqual(dataset["client_field"]["source"], "client-only")
        self.assertEqual(dataset["modality"]["enum"], ["imaging", "sequencing"])
        self.assertEqual(
            dataset["modality"]["api_enum"], ["imaging", "sequencing", "text"]
        )
        self.assertEqual(dataset["locations"]["items_model"], "asset")
        self.assertEqual(dataset["locations"]["min_items"], 1)
        self.assertNotIn(
            "locations[].location_uri", dataset
        )  # documented in asset.md instead
        self.assertTrue(dataset["governance"]["extra_allowed"])
        self.assertTrue(dataset["governance.is_pii"]["required"])
        self.assertEqual(
            dataset["governance.license"]["json_types"], ["string", "null"]
        )
        self.assertFalse(doc["models"]["dataset"]["extra_allowed"])
        self.assertIn("location_uri", doc["models"]["asset"]["fields"])

    def test_unreachable_schemas_are_ignored(self):
        self.assertNotIn("SummaryResponse", generate.reachable_schemas(fixture_spec()))
        self.assertIn("GovernanceMetadata", generate.reachable_schemas(fixture_spec()))

    def test_main_writes_snapshot_from_saved_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp, "spec.json")
            spec.write_text(json.dumps(fixture_spec()))
            out = Path(tmp, "fields.json")
            with redirect_stdout(io.StringIO()):
                code = generate.main(
                    [
                        "--spec",
                        str(spec),
                        "--no-client",
                        "--out",
                        str(out),
                        "--date",
                        "2026-01-01",
                    ]
                )
            self.assertEqual(code, 0)
            doc = json.loads(out.read_text())
            self.assertEqual(
                doc["models"]["dataset"]["fields"]["canonical_id"]["source"], "api-only"
            )

    def test_committed_snapshot_has_every_model_and_a_stamp(self):
        doc = json.loads(generate.FIELDS_JSON.read_text())
        self.assertTrue(doc["stamp"]["client_version"])
        self.assertEqual(set(doc["models"]), set(generate.MODELS))
        for model in doc["models"].values():
            for path, field in model["fields"].items():
                self.assertIn(
                    field["source"], {"both", "api-only", "client-only"}, path
                )


if __name__ == "__main__":
    unittest.main()
