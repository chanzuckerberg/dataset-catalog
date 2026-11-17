import json
import shutil
import tempfile
import unittest
from pathlib import Path

from _support import SCRIPTS, clean_env, run_script

VALIDATE = SCRIPTS / "validate_record.py"

RECORD = {
    "canonical_id": "atlas/liver/donor2",
    "name": "Mouse liver scRNA-seq, donor 2",
    "project": "CellXGene",
    "modality": "sequencing",
    "dataset_type": "processed",
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
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def validate(self, record, *args: str):
        path = self.tmp / "record.json"
        path.write_text(record if isinstance(record, str) else json.dumps(record))
        return run_script(VALIDATE, args=[str(path), *args], env=clean_env())

    def test_valid_says_only_shared_storage_was_checked(self):
        result = self.validate(RECORD)
        self.assertEqual(result.returncode, 0)
        self.assertIn("valid (shared-storage rule only;", result.stdout)
        self.assertIn("--dry-run", result.stdout)

    def test_schema_errors_are_not_reported(self):
        # Types and required fields belong to the registration script's --dry-run.
        result = self.validate({**RECORD, "modality": "microscopy"})
        self.assertEqual(result.returncode, 0)

    def test_personal_storage_is_reported(self):
        record = {
            **RECORD,
            "locations": [
                {"location_uri": "/Users/me/run/", "storage_platform": "other"}
            ],
        }
        result = self.validate(record)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not registrable", result.stdout)

    def test_other_models_check_shared_storage(self):
        asset = {"location_uri": "/Users/me/run/", "storage_platform": "other"}
        result = self.validate(asset, "--model", "asset")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.startswith("location_uri: not registrable"))
        edge = {"source_dataset_id": "a", "destination_dataset_id": "b"}
        result = self.validate(edge, "--model", "lineage")
        self.assertEqual(result.returncode, 0)

    def test_unreadable_input_exits_2(self):
        self.assertEqual(self.validate("{nope").returncode, 2)
        self.assertEqual(
            run_script(VALIDATE, args=["/no/such/file.json"]).returncode, 2
        )


if __name__ == "__main__":
    unittest.main()
