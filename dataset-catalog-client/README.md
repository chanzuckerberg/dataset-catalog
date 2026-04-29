
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

#### For CI/CD Pipelines
When installing in automated pipelines, you'll need GitHub authentication. Set up a GitHub token with repository access:

```bash
# Set the GitHub token as an environment variable
export GITHUB_TOKEN="your-github-token-here"

# Install using the token for authentication
pip install 'git+https://${GITHUB_TOKEN}@github.com/chanzuckerberg/dataset-catalog.git#subdirectory=dataset-catalog-client'
```

Make sure your GitHub token has appropriate permissions to access the repository.

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

## Documentation

See [USAGE.md](USAGE.md) for the full usage guide covering datasets, collections, lineage,
async usage, and error handling.

An interactive walkthrough is available in [examples/quickstart.ipynb](examples/quickstart.ipynb). You can start up the jupyter notebook with the following command:

```commandline
uv run jupyter notebook examples/quickstart.ipynb
```
