import copy
import json
import tempfile
import unittest
from pathlib import Path

from _support import SCRIPTS, run_script

VALIDATE = SCRIPTS / "validate_record.py"

RECORD = {
    "canonical_id": "atlas/liver/donor2",
    "name": "Mouse liver scRNA-seq, donor 2",
    "project": "CellXGene",
    "modality": "sequencing",
    "dataset_type": "processed",
    "governance": {
        "is_pii": False,
        "is_phi": False,
        "data_steward": "atlas-team",
        "access_scope": "internal",
    },
    "metadata": {
        "sample": {
            "organism": [{"label": "Mus musculus", "ontology_id": "NCBITaxon:10090"}],
            "donor_id": "D2",
        },
        "additional_metadata": {"run": 7},
    },
    "locations": [
        {
            "location_uri": "s3://b/k.h5ad",
            "asset_type": "file",
            "storage_platform": "s3",
            "size_bytes": 10,
        }
    ],
}


class ValidateRecordTest(unittest.TestCase):
    def validate(self, record, *args: str):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write(record if isinstance(record, str) else json.dumps(record))
        self.addCleanup(Path(handle.name).unlink)
        return run_script(VALIDATE, args=[handle.name, "--no-cli", *args])

    def test_valid_record(self):
        result = self.validate(RECORD)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "valid"))

    def test_errors_use_dotted_paths_with_numeric_indices(self):
        bad = copy.deepcopy(RECORD)
        del bad["locations"][0]["location_uri"]
        bad["modality"] = "mass_spec"
        bad["governance"]["is_pii"] = None
        bad["locations"].append(
            {
                "location_uri": "x",
                "asset_type": "file",
                "storage_platform": "s3",
                "size_bytes": "big",
            }
        )
        lines = self.validate(bad).stdout.splitlines()
        self.assertIn("locations.0.location_uri: Field required", lines)
        self.assertIn(
            "modality: Input should be 'imaging', 'sequencing', 'mass spec', 'text' or 'unknown'",
            lines,
        )
        self.assertIn("governance.is_pii: Input should be a valid boolean", lines)
        self.assertIn("locations.1.size_bytes: Input should be a valid integer", lines)

    def test_unknown_keys_on_closed_models_are_blocking(self):
        bad = copy.deepcopy(RECORD)
        bad["descripton"] = "typo"
        bad["locations"][0]["checksum_algo"] = "md5"
        result = self.validate(bad)
        self.assertEqual(result.returncode, 1)
        self.assertIn("descripton: Extra inputs are not permitted", result.stdout)
        self.assertIn(
            "locations.0.checksum_algo: Extra inputs are not permitted", result.stdout
        )

    def test_extra_keys_allowed_in_open_blocks(self):
        self.assertEqual(
            self.validate(RECORD).returncode, 0
        )  # sample.donor_id, metadata.additional_metadata

    def test_required_list_minimum_and_nested_required(self):
        bad = copy.deepcopy(RECORD)
        bad["locations"] = []
        del bad["governance"]["data_steward"]
        out = self.validate(bad).stdout
        self.assertIn(
            "locations: List should have at least 1 item after validation, not 0", out
        )
        self.assertIn("governance.data_steward: Field required", out)

    def test_non_object_payload_reports_root(self):
        result = self.validate([1, 2])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout.strip(), "<root>: Input should be a valid dictionary"
        )

    def test_other_models(self):
        edge = {
            "source_dataset_id": "a",
            "destination_dataset_id": "b",
            "lineage_type": "derived_from",
        }
        out = self.validate(edge, "--model", "lineage").stdout
        self.assertIn(
            "lineage_type: Input should be 'version_of', 'transformed_from' or 'copy_of'",
            out,
        )

    def test_unreadable_input_exits_2(self):
        self.assertEqual(self.validate("{nope").returncode, 2)
        self.assertEqual(
            run_script(VALIDATE, args=["/no/such/file.json"]).returncode, 2
        )


if __name__ == "__main__":
    unittest.main()
