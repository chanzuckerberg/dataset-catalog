# Installing the client

Python 3.11+, never the system interpreter. The access check (`check_auth.sh`, auth skill) already
sets this up: it reuses an active virtual environment or `./.venv`, and otherwise creates `./.venv`
with uv and installs the latest released client. Install by hand only to upgrade, to use a repo
that manages its own environment (in this monorepo, `uv sync --all-groups`), or where uv is
unavailable. Install a released tag, never `main`:

```bash
TAG=$(gh release list --repo chanzuckerberg/dataset-catalog --json tagName,publishedAt \
  --jq 'map(select(.tagName | startswith("catalog-client-v"))) | sort_by(.publishedAt) | reverse | .[0].tagName')
python -m venv .venv && source .venv/bin/activate
pip install "git+https://github.com/chanzuckerberg/dataset-catalog.git@${TAG}#subdirectory=dataset-catalog-client"
```

This installs the `catalog_client` package and the `catalog` CLI. Generated scripts need
`catalog-client>=1.3.0,<2`; the PEP 723 header records that, but because the client is installed from
git rather than a package index, install it as above rather than relying on `uv run` to resolve it.
If the installed client's `record_schema_version` is behind the `Current` row in the repo's
`schema/README.md`, re-run the install with `--upgrade`; if the newest release is still behind, the
release has not shipped yet: register against the installed version and tell the user.
