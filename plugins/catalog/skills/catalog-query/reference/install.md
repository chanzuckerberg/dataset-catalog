# Installing the catalog client (CLI + SDK)

The **`catalog` CLI and the `catalog_client` SDK** ship in one package, so a single install gives you
both. You need this install only for their conveniences — automated fan-out/union, page iteration, typed
post-processing. The common reads (search, list, get) run on the Python standard library with **no
install** (see the Quick start in `SKILL.md` and [reference/rest.md](rest.md)); that stdlib REST path is
the default for simple reads, not a fallback.

- Before any `pip install`: ask the user whether to use a virtual environment; never install into the
  system interpreter silently. Skip only inside an already-activated venv or a monorepo-managed env.
- **Install a tagged release, never `main`** — `main` is unreleased and may not match a published
  schema. Resolve the latest `catalog-client-v<X.Y.Z>` tag first, then install that exact tag.

```bash
# resolve the latest released tag (requires the gh CLI):
TAG=$(gh release list --repo chanzuckerberg/dataset-catalog \
  --json tagName,publishedAt \
  --jq 'map(select(.tagName | startswith("catalog-client-v"))) | sort_by(.publishedAt) | reverse | .[0].tagName')
echo "latest release: $TAG"   # e.g. catalog-client-v0.4.0
```

```bash
# monorepo dev — uv manages the environment (no manual venv needed):
uv sync --all-groups            # then run via `uv run python ...` / `uv run catalog ...`

# standalone — create + activate a venv FIRST, then install the tagged release:
python -m venv .venv            # or: uv venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install "git+https://github.com/chanzuckerberg/dataset-catalog.git@${TAG}#subdirectory=dataset-catalog-client"
```

This installs the `catalog_client` package (importable SDK) and the read-only `catalog` console script.
Requires Python ≥3.12. The bundled `scripts/*.py` need only this package plus the Python standard
library — no extra dependencies.
