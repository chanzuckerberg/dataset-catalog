# Installing the catalog client

The `catalog` CLI and `catalog_client` Python SDK are distributed together.

Most read operations: search, list, and get use the Python standard library and require no client installation. Install the client package only when you need:

* automatic fan-out and result union
* pagination helpers
* typed post-processing

## Before installing

* Do not install into the system Python interpreter.
* Ask whether to create a virtual environment unless one is already active or the repository manages its own environment.
* Install a released version, never `main`.
* Resolve the latest `catalog-client-v<X.Y.Z>` release tag and install that exact tag.
* Python 3.12 or newer is required.

```bash
# resolve the latest released tag (requires the gh CLI):
TAG=$(gh release list --repo chanzuckerberg/dataset-catalog \
  --json tagName,publishedAt \
  --jq 'map(select(.tagName | startswith("catalog-client-v"))) | sort_by(.publishedAt) | reverse | .[0].tagName')
echo "latest release: $TAG"   # e.g. catalog-client-v0.4.0
```

```bash
# standalone — create + activate a venv FIRST, then install the tagged release:
python -m venv .venv            # or: uv venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install "git+https://github.com/chanzuckerberg/dataset-catalog.git@${TAG}#subdirectory=dataset-catalog-client"
```

This installs:

- the catalog_client Python package
- the read-only catalog CLI

The bundled `scripts/*.py` require only this package and the Python standard library.
