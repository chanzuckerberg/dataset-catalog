
# catalog-client

Python client library for the Scientific Dataset Catalog API.

## Installation


### From GitHub (development)
```bash
pip install 'git+https://github.com/chanzuckerberg/dataset-catalog.git#subdirectory=dataset-catalog-client'
```

#### With development dependencies
```bash
pip install 'git+https://github.com/chanzuckerberg/dataset-catalog.git#subdirectory=dataset-catalog-client[dev]'
```
#### With uv and via ssh (for example, exec'd onto HPC)
```bash
 uv pip install 'git+ssh://github.com/chanzuckerberg/dataset-catalog.git#subdirectory=dataset-catalog-client'
```

### Pin to a specific version

The installs above track the latest commit on the default branch. For reproducible
environments, pin to a released tag by adding `@<tag>` before `#subdirectory`. Release
tags use the form `catalog-client-v<version>` (e.g. `catalog-client-v0.3.0`):

```bash
pip install 'git+https://github.com/chanzuckerberg/dataset-catalog.git@catalog-client-v0.3.0#subdirectory=dataset-catalog-client'
```

You can pin to any git ref the same way — a branch name or a full commit SHA:

```bash
# Pin to a commit
pip install 'git+https://github.com/chanzuckerberg/dataset-catalog.git@ccfec2008d225a919d1c6591f5d3649d112a5022#subdirectory=dataset-catalog-client'
```

See the [list of releases](https://github.com/chanzuckerberg/dataset-catalog/releases)
for available versions.

## Getting an API Token

Before using the client, you need to generate an API token:

1. Navigate to your catalog instance's API documentation (typically at `https://datacatalog.staging-sci-data.staging.czi.team/docs`)
2. Find the **Token** section in the API documentation
3. Use the `/token/issue` endpoint in the docs interface to generate a new API token
4. Copy the generated token and use it in the `api_token` parameter when creating the client

Store your token securely as it provides access to your catalog instance.

## Quick start

```python
from catalog_client import CatalogClient, DatasetModality, AssetType, OntologyEntry

with CatalogClient(base_url="https://your-catalog.example.com", api_token="your-token") as client:
    resp = client.datasets.list(limit=5)
    print(f"Found = {len(resp.results)}")
```

To export a flat manifest of all assets in a collection:

```python
from catalog_client import CatalogClient
from catalog_client.utils.manifest import MetadataFieldSpec, generate_manifest

client = CatalogClient(base_url="https://your-catalog.example.com", api_token="your-token")
result = generate_manifest(
    client,
    collection_id="<collection-uuid>",
    metadata_fields=[
        MetadataFieldSpec("experiment.sub_modality", alias="modality"),
        MetadataFieldSpec("split"),
    ],
)
print(f"{result.stats.total_rows} rows from {result.stats.total_datasets} datasets")
```

See [catalog_client/utils/manifest/README.md](catalog_client/utils/manifest/README.md) for the full manifest generation guide.

## Command-line interface

Installing the package also installs a read-only `catalog` command for querying the catalog from the shell:

```bash
export CATALOG_API_URL=https://your-catalog.example.com
export CATALOG_API_TOKEN=your-token

catalog search --q "brightfield" --organism "Homo sapiens"
catalog facets --fields organism,tissue,assay,project
catalog get <dataset-uuid> --lineage
catalog lineage <dataset-uuid> --direction up
```

Output is a human-readable table on a terminal and JSON when piped (override with `-o table|json`). See the [CLI section of USAGE.md](USAGE.md#command-line-interface) for all subcommands, flags, and exit codes.

## Documentation

| Document | Description |
|----------|-------------|
| [USAGE.md](USAGE.md) | Full usage guide — datasets, collections, lineage, async, error handling |
| [schema/v1.4.0/schema.md](../schema/v1.4.0/schema.md) | Authoritative field-level reference for the catalog schema (Data Asset, Dataset, Collection, Lineage) |
| [schema/CHANGELOG.md](../schema/CHANGELOG.md) | Schema version history and migration notes |
| [catalog_client/utils/manifest/README.md](catalog_client/utils/manifest/README.md) | Manifest generation — user guide and developer reference |

An interactive walkthrough is available in [examples/quickstart.ipynb](examples/quickstart.ipynb). Start it with:

```commandline
uv run jupyter notebook examples/quickstart.ipynb
```
