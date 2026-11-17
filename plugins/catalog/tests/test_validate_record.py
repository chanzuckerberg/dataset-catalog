import json
import os
import shutil
import stat
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
        self.bin = self.tmp / "bin"
        self.bin.mkdir()

    def fake_cli(self, stdout: str, code: int) -> None:
        cli = self.bin / "catalog"
        cli.write_text(
            f"#!/bin/sh\ncat >/dev/null\nprintf '%s' '{stdout}'\nexit {code}\n"
        )
        cli.chmod(cli.stat().st_mode | stat.S_IEXEC)

    def validate(self, record, *args: str):
        path = self.tmp / "record.json"
        path.write_text(record if isinstance(record, str) else json.dumps(record))
        env = clean_env(PATH=f"{self.bin}{os.pathsep}/usr/bin:/bin")
        return run_script(VALIDATE, args=[str(path), *args], env=env)

    def test_cli_valid(self):
        self.fake_cli("valid\n", 0)
        result = self.validate(RECORD)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "valid"))

    def test_cli_errors_are_reported(self):
        self.fake_cli("modality: Input should be sequencing or imaging\n", 1)
        result = self.validate(RECORD)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stdout.strip(), "modality: Input should be sequencing or imaging"
        )

    def test_without_cli_says_only_shared_storage_was_checked(self):
        result = self.validate(RECORD)
        self.assertEqual(result.returncode, 0)
        self.assertIn(
            "valid (shared-storage rule only: the `catalog` CLI is not installed",
            result.stdout,
        )
        result = self.validate(RECORD, "--no-cli")
        self.assertIn("--no-cli was passed", result.stdout)

    def test_other_models_check_shared_storage_only(self):
        self.fake_cli("should not run\n", 1)
        asset = {"location_uri": "/Users/me/run/", "storage_platform": "other"}
        result = self.validate(asset, "--model", "asset")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.startswith("location_uri: not registrable"))
        edge = {"source_dataset_id": "a", "destination_dataset_id": "b"}
        result = self.validate(edge, "--model", "lineage")
        self.assertIn("lineage records have no CLI check", result.stdout)

    def test_unreadable_input_exits_2(self):
        self.assertEqual(self.validate("{nope").returncode, 2)
        self.assertEqual(
            run_script(VALIDATE, args=["/no/such/file.json"]).returncode, 2
        )


if __name__ == "__main__":
    unittest.main()
