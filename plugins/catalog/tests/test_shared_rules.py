import ast
import json
import re
import unittest
import urllib.parse

from _support import SCRIPTS, TEMPLATE, run_script

VALIDATOR = SCRIPTS / "validate_record.py"
ENV_MODULE = SCRIPTS / "_env.py"
RULE_NAMES = ("CLUSTER_PLATFORMS", "PERSONAL_PATH_PREFIXES", "location_problem")
ENV_NAMES = ("env_from_url",)


def load_rule(path, names=RULE_NAMES):
    # The template imports catalog_client, so lift just the rule out of each file instead of importing it.
    tree = ast.parse(path.read_text())
    nodes = [
        node
        for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name in names)
        or (
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) in names for t in node.targets)
        )
    ]
    namespace: dict = {"re": re, "urllib": urllib}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    return namespace, [ast.unparse(node) for node in nodes]


CASES = {
    ("s3://czi-imaging/screen-07/", "s3"): False,
    ("https://data.example.org/ref/", "external"): False,
    ("/hpc/projects/atlas/liver/", "sf_hpc"): False,
    ("/mnt/shared/run-3/", "kelp"): False,
    ("file:///Users/me/data/", "other"): True,
    ("data/sample-A", "sf_hpc"): True,
    ("~/data/sample-A", "sf_hpc"): True,
    ("/Users/me/Desktop/run/", "other"): True,
    ("/hpc/projects/atlas/", "other"): True,
    ("/hpc/projects/atlas/", "s3"): True,
    ("/home/me/run/", "sf_hpc"): True,
    ("/tmp/run/", "chi_hpc"): True,
    ("/Volumes/USB/run/", "ny_hpc"): True,
}


class LocationRuleTest(unittest.TestCase):
    def test_template_and_validator_share_one_rule(self):
        _, template_src = load_rule(TEMPLATE)
        _, validator_src = load_rule(VALIDATOR)
        self.assertEqual(len(template_src), len(RULE_NAMES))
        self.assertEqual(template_src, validator_src)

    def test_rule_blocks_local_and_personal_locations(self):
        rule, _ = load_rule(TEMPLATE)
        for (uri, platform), blocked in CASES.items():
            problem = rule["location_problem"](uri, platform)
            self.assertEqual(
                problem is not None, blocked, f"{uri} on {platform}: {problem}"
            )

    def test_validator_reports_dataset_locations(self):
        record = {
            "locations": [
                {"location_uri": "s3://bucket/ok/", "storage_platform": "s3"},
                {"location_uri": "/Users/me/run/", "storage_platform": "other"},
            ]
        }
        result = run_script(VALIDATOR, json.dumps(record), args=["-"])
        self.assertEqual(result.returncode, 1)
        lines = [
            line for line in result.stdout.splitlines() if "not registrable" in line
        ]
        self.assertEqual(len(lines), 1)
        self.assertTrue(
            lines[0].startswith("locations.1.location_uri: not registrable")
        )


ENV_CASES = {
    "https://diverse-oarfish.dev-sci-data.dev.czi.team": "dev",
    "https://datacatalog.staging-sci-data.staging.czi.team": "staging",
    "https://datacatalog.prod-sci-data.prod.czi.team/": "prod",
    "https://catalog.production.example.org": "prod",
    "https://catalog.example.com": "unknown",
    "https://datacatalog.staging-sci-data.prod.czi.team": "unknown",
    "": "unknown",
}


class EnvNamingRuleTest(unittest.TestCase):
    def test_template_and_env_module_share_one_rule(self):
        _, template_src = load_rule(TEMPLATE, ENV_NAMES)
        _, env_src = load_rule(ENV_MODULE, ENV_NAMES)
        self.assertEqual(len(template_src), len(ENV_NAMES))
        self.assertEqual(template_src, env_src)

    def test_env_named_from_hostname(self):
        rule, _ = load_rule(TEMPLATE, ENV_NAMES)
        for url, env in ENV_CASES.items():
            self.assertEqual(rule["env_from_url"](url), env, url)


if __name__ == "__main__":
    unittest.main()
