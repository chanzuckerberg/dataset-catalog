import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from _support import SCRIPTS, clean_env

sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("check_auth", SCRIPTS / "check_auth.py")
assert _spec and _spec.loader
check_auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_auth)

TOKEN = "staging-token-value-123"
STAGING = "https://datacatalog.staging-sci-data.staging.czi.team"
ENV = clean_env(CATALOG_API_URL=STAGING + "/", CATALOG_API_TOKEN=TOKEN)


def fake_get(routes: dict):
    def get(url, token):
        assert token == TOKEN
        path = url.split(".czi.team", 1)[1]
        return routes.get(path, (404, {"detail": "Not Found"}))

    return get


class CheckAuthTest(unittest.TestCase):
    def run_check(self, routes: dict, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with (
            mock.patch.dict(os.environ, ENV, clear=True),
            mock.patch.object(check_auth, "get", fake_get(routes)),
            mock.patch.object(check_auth, "client_version", lambda: "1.3.0"),
            redirect_stdout(out),
        ):
            code = check_auth.main(list(args))
        return code, out.getvalue()

    def validate_body(self, permissions):
        return {
            "token": {
                "name": "laptop",
                "token_prefix": "abcd1234",
                "is_active": True,
                "permissions": permissions,
                "expires_at": "2027-01-01T00:00:00Z",
            },
            "user": {
                "name": "Ada",
                "team": "imaging",
                "email": "ada@example.org",
                "id": "u1",
            },
        }

    def test_v1_validate_reports_identity_and_write(self):
        code, out = self.run_check(
            {"/api/v1/token/validate": (200, self.validate_body("rw"))}
        )
        self.assertEqual(code, 0)
        self.assertRegex(out, r"environment\s+staging \(from CATALOG_API_URL\)")
        self.assertRegex(out, rf"catalog URL\s+{STAGING}\n")
        self.assertRegex(out, r"token source\s+CATALOG_API_TOKEN\n")
        self.assertIn("Ada (imaging)", out)
        self.assertRegex(out, r"write\s+yes")
        self.assertIn("2027-01-01", out)
        self.assertNotIn("abcd1234", out)
        self.assertNotIn("ada@example.org", out)
        self.assertNotIn(TOKEN, out)

    def test_null_permissions_are_read_only_and_email_only_verbose(self):
        code, out = self.run_check(
            {"/api/v1/token/validate": (200, self.validate_body(None))}, "--verbose"
        )
        self.assertEqual(code, 0)
        self.assertRegex(out, r"write\s+no")
        self.assertIn("ada@example.org", out)

    def test_rejected_token_exits_2(self):
        code, out = self.run_check(
            {"/api/v1/token/validate": (401, {"detail": "Invalid or expired token"})}
        )
        self.assertEqual(code, 2)
        self.assertIn("Invalid or expired token", out)

    def test_old_deployment_falls_back_without_guessing_write(self):
        code, out = self.run_check(
            {
                "/token/validate": (200, None),
                "/api/v1/datasets/?limit=1": (200, {"results": []}),
            }
        )
        self.assertEqual(code, 0)
        self.assertRegex(out, r"read\s+yes")
        self.assertIn("unknown — needs /api/v1/token/validate", out)

    def test_unreachable_exits_1(self):
        def boom(url, token):
            raise check_auth.Unreachable("timed out")

        with (
            mock.patch.object(check_auth, "get", boom),
            mock.patch.dict(os.environ, ENV, clear=True),
            redirect_stdout(io.StringIO()),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(check_auth.main([]), 1)

    def test_missing_token_and_unknown_host(self):
        with mock.patch.object(check_auth, "client_version", lambda: None):
            rows, code = check_auth.check("https://catalog.example.com", None, False)
        rows = dict(rows)
        self.assertEqual(code, 2)
        self.assertIn("treated as production", rows["environment"])
        self.assertEqual(
            rows["token source"], "none — set CATALOG_API_TOKEN for this catalog"
        )


if __name__ == "__main__":
    unittest.main()


class CheckAuthShellTest(unittest.TestCase):
    """check_auth.sh: credentials first, then a Python environment, then check_auth.py."""

    SCRIPT = SCRIPTS / "check_auth.sh"
    # Connection refused: proves check_auth.py ran without touching the network.
    UNREACHABLE = "http://127.0.0.1:9"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_sh(self, *args: str, path: str | None = None, **env: str):
        environ = {k: v for k, v in clean_env(**env).items() if k != "VIRTUAL_ENV"}
        if path is not None:
            environ["PATH"] = path
        return subprocess.run(
            [str(self.SCRIPT), *args],
            capture_output=True,
            text=True,
            env=environ,
            cwd=self.tmp,
            check=False,
        )

    def test_missing_credentials_stop_before_any_python_setup(self):
        result = self.run_sh(CATALOG_API_URL=self.UNREACHABLE)
        self.assertEqual(result.returncode, 2)
        self.assertIn("CATALOG_API_TOKEN not set", result.stderr)
        self.assertFalse((self.tmp / ".venv").exists())
        report = self.run_sh("--report")
        self.assertEqual(report.returncode, 0)
        self.assertIn("CATALOG_API_URL and CATALOG_API_TOKEN not set", report.stdout)

    def test_existing_venv_is_used(self):
        bin_dir = self.tmp / ".venv" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "python").symlink_to(sys.executable)
        result = self.run_sh(
            CATALOG_API_URL=self.UNREACHABLE, CATALOG_API_TOKEN="fake-token-123"
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("could not reach http://127.0.0.1:9", result.stderr)
        self.assertNotIn("creating", result.stderr)

    def test_without_uv_falls_back_to_system_python(self):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "python3").symlink_to(sys.executable)
        result = self.run_sh(
            "--report",
            path=f"{bin_dir}:/usr/bin:/bin",
            CATALOG_API_URL=self.UNREACHABLE,
            CATALOG_API_TOKEN="fake-token-123",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("uv is not installed", result.stdout)
        self.assertIn("could not reach", result.stdout)
        self.assertFalse((self.tmp / ".venv").exists())
