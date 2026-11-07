"""The registration template's own logic, against a stub catalog_client (the real SDK is not a plugin dependency)."""

import importlib.util
import io
import json
import logging
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from _support import TEMPLATE, clean_env

STAGING = "https://datacatalog.staging-sci-data.staging.czi.team"


class CompatibilityError(Exception):
    pass


class Report:
    def __init__(self, ok: int, failed: list[str]):
        self.ok, self.failed = ok, failed
        self.exit_code = 1 if failed else 0

    def summary(self, verb: str = "registered") -> str:
        return f"{self.ok} {verb}, {len(self.failed)} failed" + (
            ": " + ", ".join(self.failed) if self.failed else ""
        )


def run_batch(items, handle, *, key=str, max_workers=4, logger=None):
    ok, failed = 0, []
    for item in items:
        try:
            handle(item)
            ok += 1
        except Exception as exc:  # noqa: BLE001 - mirrors per-item isolation
            failed.append(f"{key(item)} ({type(exc).__name__})")
    return Report(ok, failed)


class FakeClient:
    instances: list["FakeClient"] = []
    compatible = True

    def __init__(self, base_url, api_token, retry=None, timeout=30.0):
        self.base_url, self.api_token, self.retry = base_url, api_token, retry
        self.calls: list[tuple] = []
        self.collections = types.SimpleNamespace(
            get=lambda cid: self.calls.append(("collections.get", cid)),
            add_dataset=lambda cid, did: self.calls.append(
                ("collections.add_dataset", cid, did)
            ),
        )
        FakeClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def plan(self, request, update_if_exists=False, error_on_duplicate=True):
        self.calls.append(("plan", request.key, update_if_exists, error_on_duplicate))
        edge = types.SimpleNamespace(
            lineage_type=types.SimpleNamespace(value="transformed_from"),
            source_dataset_id="parent-1",
            destination_dataset_id="",
        )
        return types.SimpleNamespace(
            action="create", dataset_id=None, lineage_to_create=[edge], request=request
        )

    def register(self, request, update_if_exists=False, error_on_duplicate=True):
        self.calls.append(
            ("register", request.key, update_if_exists, error_on_duplicate)
        )
        return f"id-{request.key}"


def check_compatibility(client):
    if not FakeClient.compatible:
        raise CompatibilityError("server record schema v9 is newer than client v1.7.0")


def install_stub_sdk() -> None:
    names = [
        "catalog_client",
        "catalog_client.models",
        "catalog_client.models.asset",
        "catalog_client.registration",
        "catalog_client.utils",
        "catalog_client.utils.checksum",
    ]
    mods = {name: types.ModuleType(name) for name in names}
    attrs: dict[str, dict[str, object]] = {
        "catalog_client": {
            "CatalogClient": FakeClient,
            "CompatibilityError": CompatibilityError,
            "RetryPolicy": lambda **kw: ("RetryPolicy", kw),
            "check_compatibility": check_compatibility,
            "run_batch": run_batch,
            **{
                name: mock.MagicMock(name=name)
                for name in (
                    "AssetType",
                    "DatasetModality",
                    "DatasetRef",
                    "DatasetType",
                    "LineageType",
                    "OntologyEntry",
                )
            },
        },
        "catalog_client.models.asset": {
            name: mock.MagicMock(name=name)
            for name in ("DataAssetRequest", "StoragePlatform")
        },
        "catalog_client.registration": {
            name: mock.MagicMock(name=name)
            for name in ("LineageSpec", "RegistrationBuilder", "RegistrationRequest")
        },
        "catalog_client.utils.checksum": {
            name: mock.MagicMock(name=name)
            for name in ("Algorithm", "compute_checksum")
        },
    }
    for module_name, values in attrs.items():
        for attr, value in values.items():
            setattr(mods[module_name], attr, value)
    sys.modules.update(mods)


class FakeRequest:
    def __init__(self, key: str, valid: bool = True):
        self.key, self.valid = key, valid

    def to_dataset_request(self):
        if not self.valid:
            raise ValueError("governance.is_pii: Input should be a valid boolean")
        return types.SimpleNamespace(model_dump=lambda **kw: {"canonical_id": self.key})


def load_template():
    install_stub_sdk()
    spec = importlib.util.spec_from_file_location("register_template", TEMPLATE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = (
        module  # dataclasses resolves annotations through sys.modules
    )
    spec.loader.exec_module(module)
    return module


class TemplateTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_template()
        FakeClient.instances.clear()
        FakeClient.compatible = True
        self.tmp = Path(tempfile.mkdtemp())
        self.config = self.tmp / "mapping.json"
        self.config.write_text(json.dumps({"collections": ["col-1"]}))
        self.keys = ["a", "b", "c"]
        self.invalid: set[str] = set()
        self.mod.discover_records = lambda config: (
            self.mod.Source(key=k) for k in self.keys
        )
        self.mod.build_request = lambda src, config: FakeRequest(
            src.key, src.key not in self.invalid
        )

    def run_main(self, *args: str, env: dict | None = None) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        environ = (
            env
            if env is not None
            else clean_env(CATALOG_STAGING_API_TOKEN="tok-staging")
        )
        # basicConfig binds stderr only once per process, so capture the script's logger directly.
        handler = logging.StreamHandler(err)
        self.mod.log.addHandler(handler)
        try:
            with (
                mock.patch.dict(os.environ, environ, clear=True),
                redirect_stdout(out),
                redirect_stderr(err),
            ):
                code = self.mod.main(
                    [
                        "--config",
                        str(self.config),
                        "--payload-dir",
                        str(self.tmp / "payloads"),
                        *args,
                    ]
                )
        finally:
            self.mod.log.removeHandler(handler)
        return code, out.getvalue(), err.getvalue()

    def test_defaults_to_staging_with_retry_policy(self):
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        client = FakeClient.instances[0]
        self.assertEqual((client.base_url, client.api_token), (STAGING, "tok-staging"))
        self.assertEqual(
            client.retry[1],
            {"max_attempts": 5, "base_delay": 0.5, "max_delay": 30.0, "jitter": True},
        )
        self.assertIn("3 registered, 0 failed", out)

    def test_register_is_an_idempotent_upsert_and_adds_collections(self):
        self.run_main()
        calls = FakeClient.instances[0].calls
        self.assertIn(("register", "a", True, False), calls)
        self.assertIn(("collections.add_dataset", "col-1", "id-a"), calls)
        self.assertFalse([c for c in calls if c[0] == "plan"])

    def test_dry_run_plans_only_writes_payloads_and_prints_marker(self):
        code, out, err = self.run_main("--dry-run")
        self.assertEqual(code, 0)
        calls = FakeClient.instances[0].calls
        self.assertFalse(
            [c for c in calls if c[0] in ("register", "collections.add_dataset")]
        )
        self.assertIn(("plan", "a", True, False), calls)
        self.assertEqual(len(list((self.tmp / "payloads").glob("*.json"))), 3)
        self.assertIn("3 planned, 0 failed", out)
        self.assertIn("catalog-dry-run: ok env=staging", out)
        self.assertIn(f"config={self.config.resolve()}", out)
        self.assertIn("-> (new dataset)", err)

    def test_one_bad_record_does_not_stop_the_batch(self):
        self.invalid = {"b"}
        code, out, _ = self.run_main("--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("2 planned, 1 failed: b (ValueError)", out)
        self.assertNotIn("catalog-dry-run: ok", out)
        self.assertNotIn(("plan", "b", True, False), FakeClient.instances[0].calls)

    def test_limit(self):
        self.run_main("--limit", "1")
        self.assertEqual(
            [c[1] for c in FakeClient.instances[0].calls if c[0] == "register"], ["a"]
        )

    def test_missing_token_and_compatibility_exit_2_before_any_record(self):
        code, _, err = self.run_main(env=clean_env())
        self.assertEqual(code, 2)
        self.assertIn("CATALOG_STAGING_API_TOKEN", err)
        self.assertFalse(FakeClient.instances)
        FakeClient.compatible = False
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("client/API mismatch", err)
        self.assertFalse(FakeClient.instances[-1].calls)

    def test_prod_needs_its_own_token(self):
        env = clean_env(CATALOG_API_TOKEN="generic", CATALOG_API_URL=STAGING)
        self.assertEqual(self.run_main("--env", "prod", env=env)[0], 2)
        env = clean_env(CATALOG_PROD_API_TOKEN="tok-prod")
        self.assertEqual(self.run_main("--env", "prod", env=env)[0], 0)
        self.assertEqual(
            FakeClient.instances[-1].base_url,
            "https://datacatalog.prod-sci-data.prod.czi.team",
        )

    def test_bad_arguments_and_config(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.mod.parse_args(["--workers", "64"])
        self.config.write_text("{not json")
        self.assertEqual(self.run_main()[0], 2)


if __name__ == "__main__":
    unittest.main()
