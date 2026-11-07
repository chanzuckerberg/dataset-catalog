import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

from _support import SCRIPTS, clean_env

sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location("check_auth", SCRIPTS / "check_auth.py")
assert _spec and _spec.loader
check_auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_auth)

TOKEN = "staging-token-value-123"
STAGING = "https://datacatalog.staging-sci-data.staging.czi.team"


def fake_get(routes: dict):
    def get(url, token):
        assert token == TOKEN
        path = url.split(".czi.team", 1)[1]
        return routes.get(path, (404, {"detail": "Not Found"}))

    return get


class CheckAuthTest(unittest.TestCase):
    def run_check(self, routes: dict, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        env = clean_env(CATALOG_STAGING_API_TOKEN=TOKEN)
        with (
            mock.patch.dict(os.environ, env, clear=True),
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
        self.assertIn("CATALOG_STAGING_API_TOKEN", out)
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
            mock.patch.dict(
                os.environ, clean_env(CATALOG_STAGING_API_TOKEN=TOKEN), clear=True
            ),
            redirect_stdout(io.StringIO()),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(check_auth.main([]), 1)

    def test_generic_token_needs_matching_url(self):
        with mock.patch.dict(
            os.environ, clean_env(CATALOG_API_TOKEN=TOKEN), clear=True
        ):
            self.assertEqual(check_auth.resolve_token("staging"), (None, None))
        with mock.patch.dict(
            os.environ,
            clean_env(CATALOG_API_TOKEN=TOKEN, CATALOG_API_URL=STAGING + "/"),
            clear=True,
        ):
            self.assertEqual(
                check_auth.resolve_token("staging"), ("CATALOG_API_TOKEN", TOKEN)
            )
            self.assertEqual(check_auth.resolve_token("prod"), (None, None))


if __name__ == "__main__":
    unittest.main()
