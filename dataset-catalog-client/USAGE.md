# catalog-client Usage Guide

Python client library for the Scientific Dataset Catalog API.

## Setup

All `/api/` endpoints require an `X-catalog-api-token` header. Obtain a token from your
catalog administrator, then pass it when constructing the client.

```python
from catalog_client import CatalogClient

client = CatalogClient(
    base_url="https://your-catalog.example.com",
    api_token="your-token-here",
    timeout=30.0,  # optional, default 30 s
)
```

Use the client as a context manager to ensure the HTTP connection is closed:

```python
with CatalogClient(base_url="...", api_token="...") as client:
    ...
```

An async variant is also available — see [Async usage](#async-usage).

---

## Datasets

### Create a dataset

`DatasetCreate` requires `canonical_id`, `name`, `modality`, `locations` (≥ 1 asset),
`governance`, and `metadata`. Everything else is optional.

```python
from catalog_client import (
    CatalogClient,
    DatasetCreate,
    DatasetModality,
    DataAssetRequest,
    AssetType,
    GovernanceMetadata,
    DatasetMetadata,
)

with CatalogClient(base_url="...", api_token="...") as client:
    dataset = client.datasets.create(DatasetCreate(
        canonical_id="my-rna-seq-dataset",
        name="RNA-seq batch 42",
        version="1.0.0",
        modality=DatasetModality.sequencing,
        locations=[
            DataAssetRequest(
                location_uri="s3://my-bucket/rna-seq/batch42/",
                asset_type=AssetType.folder,
            )
        ],
        governance=GovernanceMetadata(
            data_owner="genomics-team",
            data_sensitivity="internal",
            is_pii=False,
        ),
        metadata=DatasetMetadata(),
    ))
    print(dataset.id)
```

### Registration builder (recommended)

`new_registration()` returns a fluent builder that constructs and submits the dataset in one chain:

```python
from catalog_client import CatalogClient, DatasetModality, AssetType, OntologyEntry, LineageType

with CatalogClient(base_url="...", api_token="...") as client:
    dataset_id = (
        client.new_registration(
            canonical_id="my-rna-seq-dataset",
            name="RNA-seq batch 42",
            version="1.0.0",
            project="atlas",
            modality=DatasetModality.sequencing,
        )
        .described("Bulk RNA-seq from PBMC donors, batch 42.")
        .with_location("s3://my-bucket/rna-seq/batch42/", asset_type=AssetType.folder)
        .with_governance(data_owner="genomics-team", is_pii=False)
        .with_sample(
            organism=[OntologyEntry(label="Homo sapiens", ontology_id="NCBITaxon:9606")]
        )
        .with_experiment(sub_modality="bulk", equipment={"sequencer": "NovaSeq 6000", "chemistry": "v4"})
        # Add dataset-level custom metadata (not tied to sample/experiment/data_summary)
        .with_custom_metadata(
            project_phase="discovery",
            funding_source="NIH Grant R01-123456",
            collaboration=["Lab A", "Lab B"]
        )
        .submit()
    )
    print(dataset_id)
```

To record lineage at registration time:

```python
    dataset_id = (
        client.new_registration(
            canonical_id="processed-rna-seq",
            name="Processed RNA-seq batch 42",
            version="1.0.0",
            project="atlas",
            modality=DatasetModality.sequencing,
        )
        .with_location("s3://my-bucket/processed/batch42/", asset_type=AssetType.folder)
        .with_governance(data_owner="genomics-team", is_pii=False)
        .with_lineage("<raw-dataset-uuid>", lineage_type=LineageType.transformed_from)
        .submit()
    )
```

### List datasets

```python
from catalog_client import DatasetModality

page = client.datasets.list(
    canonical_id="my-rna-seq-dataset",  # exact match filter
    version="1.0.0",                    # exact match filter
    modality=DatasetModality.sequencing,
    project="atlas",
    is_latest=True,
    include_lineage=False,
    include_collections=False,
    offset=0,
    limit=100,
)

print(f"{page.total} total results")
for ds in page.results:
    print(ds.id, ds.name, ds.version)
```

### Get a single dataset

```python
# By UUID
dataset = client.datasets.get("dataset-uuid")

# With sideloaded lineage and collections
dataset = client.datasets.get(
    "dataset-uuid",
    include_lineage=True,
    include_collections=True,
)
print(dataset.incoming_lineage)
print(dataset.outgoing_lineage)
print(dataset.collections)
```

You can also resolve by human-readable coordinates using `DatasetRef`:

```python
from catalog_client import DatasetRef

ref = DatasetRef(canonical_id="my-rna-seq-dataset", version="1.0.0", project="atlas")
dataset = client.datasets.get(ref)
```

### Update a dataset

PATCH applies only the fields you set (`exclude_unset=True`). Changing `canonical_id`,
`version`, or `project` tombstones the existing record and creates a new one.

```python
updated = client.datasets.update(
    "dataset-uuid",
    DatasetCreate(
        canonical_id="my-rna-seq-dataset",
        name="RNA-seq batch 42 (revised)",
        version="1.0.1",
        modality=DatasetModality.sequencing,
        locations=[...],
        governance=GovernanceMetadata(...),
        metadata=DatasetMetadata(),
    ),
)
print(updated.id)  # may differ if signature fields changed
```

### Delete (soft-delete) a dataset

```python
client.datasets.delete("dataset-uuid")  # returns None, status 204
```

---

## Collections

Collections are flat, mutable groupings of datasets (e.g. for a publication or training run).

### Create / update / delete

```python
from catalog_client import CollectionCreate, CollectionUpdate, CollectionType

col = client.collections.create(CollectionCreate(
    canonical_id="my-publication-collection",
    version="1.0.0",
    name="Nature Paper 2025 datasets",
    collection_owner="data-team",
    collection_type=CollectionType.publication,
    description="All datasets used in doi:10.1234/example",
))

updated = client.collections.update(col.id, CollectionUpdate(name="Nature Paper 2025 (final)"))

client.collections.delete(col.id)  # soft-delete, status 204
```

### List / get

```python
page = client.collections.list(offset=0, limit=100)
collection = client.collections.get("collection-uuid")
```

### Add / remove datasets

Both operations are idempotent and return the updated `CollectionResponse`.

```python
col = client.collections.add_dataset(collection_id, dataset_id)
col = client.collections.remove_dataset(collection_id, dataset_id)
```

---

## Lineage

Lineage edges are **immutable** directed relationships between two datasets. Use DELETE to
tombstone an edge recorded in error.

### Edge types

| `LineageType`       | Meaning                                                  |
|---------------------|----------------------------------------------------------|
| `version_of`        | Destination is a newer version of source                 |
| `transformed_from`  | Destination was derived by processing source             |
| `copy_of`           | Destination is a copy of source (e.g. migrated location) |

### Create an edge

```python
from catalog_client import LineageEdgeCreate, LineageType

edge = client.lineages.create(LineageEdgeCreate(
    source_dataset_id="source-uuid",
    destination_dataset_id="derived-uuid",
    lineage_type=LineageType.transformed_from,
))
print(edge.id)
```

### List / get / delete

```python
page = client.lineages.list(
    source_dataset_id="source-uuid",
    lineage_type=LineageType.transformed_from,
    offset=0,
    limit=100,
)

edge = client.lineages.get("edge-uuid")

client.lineages.delete("edge-uuid")  # soft-delete, status 204
```

---

## Async usage 
### The async implementation might still have critical bugs. It is currently recommended to use the synchronous path.

`AsyncCatalogClient` mirrors the sync API with `await`:

```python
import asyncio
from catalog_client import AsyncCatalogClient, DatasetModality

async def main():
    async with AsyncCatalogClient(base_url="...", api_token="...") as client:
        page = await client.datasets.list(modality=DatasetModality.imaging, is_latest=True)
        for ds in page.results:
            print(ds.name)

asyncio.run(main())
```

---

## Error handling

```python
from catalog_client import (
    AuthenticationError,
    NotFoundError,
    ValidationError,
    CatalogServerError,
    CatalogConnectionError,
    CatalogError,
)

try:
    dataset = client.datasets.get("missing-uuid")
except NotFoundError as e:
    print(f"404 – {e.detail}")
except AuthenticationError:
    print("Invalid or expired API token")
except ValidationError as e:
    print(f"422 – {e.detail}")
except CatalogServerError as e:
    print(f"Server error {e.status_code}")
except CatalogConnectionError as e:
    print(f"Network error: {e}")
except CatalogError as e:
    print(f"Unexpected catalog error: {e}")
```

---

## Key models reference

| Model | Used for |
|---|---|
| `DatasetCreate` | Creating or updating a dataset |
| `DatasetResponse` | Return value from create / update |
| `DatasetWithRelationsResponse` | Return value from get / list (includes optional lineage + collections) |
| `DataAssetRequest` | Asset entry inside `DatasetCreate.locations` |
| `DataAssetResponse` | Asset entry inside response `locations` |
| `GovernanceMetadata` | Access control and ownership info |
| `DatasetMetadata` | Top-level metadata envelope (`experiment`, `sample`, `data_summary`) |
| `SampleMetadata` | Biological sample information |
| `ExperimentMetadata` | Experimental setup and instrument info |
| `DataSummaryMetadata` | Content descriptors and modality-specific measurements |
| `DataQualityChecks` | QC pass / fail / skipped check names |
| `CollectionCreate` | Creating a collection |
| `CollectionUpdate` | Partially updating a collection |
| `CollectionResponse` | Collection return value |
| `LineageEdgeCreate` | Creating a lineage edge |
| `LineageEdgeResponse` | Lineage edge return value |
| `PaginatedResponse[T]` | Wrapper for list endpoints (`total`, `limit`, `offset`, `results`) |

### Enums

| Enum | Values |
|---|---|
| `DatasetModality` | `imaging`, `sequencing`, `mass_spec`, `unknown` |
| `DatasetType` | `raw`, `processed` |
| `AssetType` | `file`, `folder` |
| `StoragePlatform` | `s3`, `bruno_hpc`, `hpc`, `coreweave`, `external`, `other` |
| `LineageType` | `version_of`, `transformed_from`, `copy_of` |
| `CollectionType` | `publication`, `training` |
