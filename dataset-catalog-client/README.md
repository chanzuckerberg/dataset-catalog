# catalog-client

Python client library for the Scientific Dataset Catalog API.

## Installation

```bash
pip install catalog-client
```

## Quick start

```python
from catalog_client import CatalogClient

with CatalogClient(base_url="https://your-catalog.example.com", api_token="your-token") as client:
    page = client.datasets.list_()
    for ds in page.results:
        print(ds.name, ds.version)
```

The `with` block is required when using [model fetch methods](#fetch-methods-on-models). For
plain client calls it is optional — you can also call `client.close()` manually.

---

## Datasets

### List datasets

```python
from catalog_client import CatalogClient, DatasetModality

with CatalogClient(base_url="...", api_token="...") as client:
    # All datasets (paginated)
    page = client.datasets.list_()

    # Filtered
    page = client.datasets.list_(
        modality=DatasetModality.imaging,
        project="oncology",
        skip=0,
        limit=50,
    )

    for ds in page.results:
        print(ds.name, ds.version, f"({page.total} total)")
```

### Get a single dataset

```python
dataset = client.datasets.get("dataset-uuid")
```

### Create a dataset

```python
from catalog_client import DatasetCreate, DatasetModality, DataAssetRequest, AssetType, GovernanceMetadata, DatasetMetadata

new_ds = client.datasets.create(DatasetCreate(
    canonical_id="canonical-uuid",
    name="My Dataset",
    version="1.0.0",
    modality=DatasetModality.sequencing,
    locations=[DataAssetRequest(location_uri="s3://bucket/path", asset_type=AssetType.folder)],
    governance=GovernanceMetadata(data_owner="team-x"),
    metadata=DatasetMetadata(),
))
```

### Update a dataset

```python
from catalog_client import DatasetCreate

updated = client.datasets.update(dataset.id, DatasetCreate(name="Renamed Dataset"))
```

### Delete a dataset

```python
client.datasets.delete(dataset.id)  # 204 No Content
```

---

## Collections

### List / get

```python
page = client.collections.list_(skip=0, limit=100)
collection = client.collections.get("collection-uuid")
```

### Create / update / delete

```python
from catalog_client import CollectionCreate, CollectionUpdate

new_col = client.collections.create(CollectionCreate(
    canonical_id="canonical-uuid",
    version="1.0.0",
    name="My Collection",
    collection_owner="team-x",
))

updated = client.collections.update(new_col.id, CollectionUpdate(name="Renamed"))

client.collections.delete(new_col.id)
```

### Add / remove datasets

```python
collection = client.collections.add_dataset(collection_id, dataset_id)
collection = client.collections.remove_dataset(collection_id, dataset_id)
```

---

## Lineages

### List lineage edges

```python
from catalog_client import LineageType

page = client.lineages.list_(
    source_dataset_id="dataset-uuid",
    lineage_type=LineageType.transformed_from,
    limit=20,
)
```

### Get a single edge

```python
edge = client.lineages.get("edge-uuid")
```

### Create / delete

```python
from catalog_client import LineageEdgeCreate, LineageType

new_edge = client.lineages.create(LineageEdgeCreate(
    source_dataset_id="source-uuid",
    destination_dataset_id="derived-uuid",
    lineage_type=LineageType.transformed_from,
))

client.lineages.delete(new_edge.id)  # 204 No Content
```

### Expand (bulk resolve datasets)

`expand()` fetches every unique dataset once and populates `source_dataset` and
`destination_dataset` on each edge.

```python
page = client.lineages.list_(source_dataset_id="dataset-uuid")
expanded = client.lineages.expand(page.results)

for edge in expanded:
    print(edge.source_dataset.name, "→", edge.destination_dataset.name)
```

---

## Fetch methods on models

`DatasetResponse` and `LineageEdgeResponse` objects can fetch related data without passing the
client around, as long as a `with CatalogClient(...)` block is active.

### DatasetResponse

```python
with CatalogClient(base_url="...", api_token="...") as client:
    dataset = client.datasets.get("dataset-uuid")

    # All lineage edges where this dataset is source or destination
    edges = dataset.fetch_lineages()

    # Filter by type
    transforms = dataset.fetch_lineages(lineage_type=LineageType.transformed_from)
```

### LineageEdgeResponse

```python
with CatalogClient(base_url="...", api_token="...") as client:
    edge = client.lineages.get("edge-uuid")

    src  = edge.fetch_source_dataset()       # also sets edge.source_dataset
    dest = edge.fetch_destination_dataset()  # also sets edge.destination_dataset

    # Fetch and populate both at once (uses expand() internally)
    edge.fetch_expanded()
    print(edge.source_dataset, edge.destination_dataset)
```

---

## Tokens

```python
from catalog_client import TokenIssueRequest, TokenExpiry

created = client.tokens.issue(TokenIssueRequest(
    user_name="alice",
    user_team="data-eng",
    user_email="alice@example.com",
    name="my-token",
    expiry=TokenExpiry.thirty_days,
))
print(created.token)  # shown only once

result = client.tokens.validate(created.token)
print(result.user.email)
```

---

## Error handling

```python
from catalog_client import AuthenticationError, NotFoundError, CatalogError, CatalogServerError

try:
    dataset = client.datasets.get("missing-id")
except NotFoundError as e:
    print(f"Not found: {e.detail}")
except AuthenticationError:
    print("Invalid or missing API token")
except CatalogServerError as e:
    print(f"Server error ({e.status_code})")
except CatalogError as e:
    print(f"Unexpected error: {e}")
```

---

## Context variable pattern

`CatalogClient` uses a `ContextVar` to make itself available to model fetch methods. When you
enter a `with` block the client is stored in a context variable; when the block exits it is
cleared and the HTTP connection is closed.

```python
# Inside the context — fetch methods work
with CatalogClient(base_url="...", api_token="...") as client:
    ds = client.datasets.get("dataset-uuid")
    edges = ds.fetch_lineages()  # ok

# Outside the context — raises RuntimeError
ds.fetch_lineages()  # RuntimeError: No active CatalogClient...
```

Nested clients are supported: each `with` block saves and restores the previous context variable
state, so the innermost client is always active.
