# dataset-catalog

A Python client library for the **Scientific Dataset Catalog API** — a dataset catalog system for tracking scientific datasets, their versions, lineage relationships, and collections.

## Packages

| Package | Description |
|---|---|
| [`dataset-catalog-client/`](./dataset-catalog-client/) | `catalog-client` — Python client library |

## catalog-client

### Installation

```bash
pip install catalog-client
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add catalog-client
```

### Error Handling

```python
from catalog_client import (
    CatalogError,           # base exception
    AuthenticationError,    # 401
    NotFoundError,          # 404
    ValidationError,        # 422
    CatalogServerError,     # 5xx
    LineageResolutionError, # lineage source ref could not be resolved
)
```

### Requirements

- Python >= 3.12
- `httpx` 0.28.1
- `pydantic` >= 2.10
