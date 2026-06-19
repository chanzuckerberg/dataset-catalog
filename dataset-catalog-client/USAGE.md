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

`DatasetRequest` requires `canonical_id`, `name`, `version`, `project`, `modality`, `locations` (≥ 1 asset),
`governance`, and `metadata`. Everything else is optional.

```python
from catalog_client import (
    CatalogClient,
    DatasetRequest,
    DatasetModality,
    DataAssetRequest,
    AssetType,
    GovernanceMetadata,
    DatasetMetadata,
    StoragePlatform,
)

with CatalogClient(base_url="...", api_token="...") as client:
    dataset = client.datasets.create(DatasetRequest(
        canonical_id="my-rna-seq-dataset",
        name="RNA-seq batch 42",
        version="1.0.0",
        project="SHRIMP",
        modality=DatasetModality.sequencing,
        locations=[
            DataAssetRequest(
                location_uri="s3://my-bucket/rna-seq/batch42/",
                asset_type=AssetType.folder,
                storage_platform=StoragePlatform.s3
            )
        ],
        governance=GovernanceMetadata(
            data_owner="genomics-team",
            access_scope="internal",
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
        .with_location("s3://my-bucket/rna-seq/batch42/", asset_type=AssetType.folder, storage_platform=StoragePlatform.s3)
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
        .with_location("s3://my-bucket/processed/batch42/", asset_type=AssetType.folder, storage_platform=StoragePlatform.s3)
        .with_governance(data_owner="genomics-team", is_pii=False)
        .with_lineage("<raw-dataset-uuid>", lineage_type=LineageType.transformed_from)
        .submit()
    )
```

You can also pass a `DatasetRef` instead of a UUID — it will be resolved at submission time:

```python
from catalog_client import DatasetRef

dataset_id = (
    client.new_registration(...)
    .with_location(...)
    .with_governance(data_owner="genomics-team", is_pii=False)
    .with_lineage(
        DatasetRef(canonical_id="raw-rna-seq", version="1.0.0", project="atlas"),
        lineage_type=LineageType.transformed_from,
    )
    .submit()
)
```

### Additional builder methods

The builder exposes further optional methods:

| Method | Description |
|--------|-------------|
| `.described(text)` | Set a free-text description |
| `.as_latest(bool)` | Mark as the latest version (default `True`) |
| `.of_type(DatasetType)` | Set `dataset_type` to `raw` or `processed` |
| `.with_sample(**kwargs)` | Populate `SampleMetadata` (organism, tissue, disease, …) |
| `.with_experiment(**kwargs)` | Populate `ExperimentMetadata` (sub_modality, assay, …) |
| `.with_data_summary(**kwargs)` | Populate `DataSummaryMetadata` (read_count, resolution, …) |
| `.with_data_quality(**kwargs)` | Set `DataQualityChecks` (passed, failed, skipped check names) |
| `.with_custom_metadata(**kwargs)` | Add arbitrary key-value pairs at the dataset-metadata level |
| `.with_doi(doi)` | Set the dataset DOI |
| `.with_cross_db_references(refs)` | Set external DB references (list or `; `-joined string) |
| `.with_metadata_schema(schemas)` | Set the `metadata_schema` list |
| `.with_lineage(source, lineage_type=…, metadata=None)` | Record a lineage edge (UUID string or `DatasetRef`), optionally with edge metadata |
| `.build()` | Return the `RegistrationRequest` without submitting |

### Handling duplicate datasets

By default, attempting to register a dataset that already exists (same `canonical_id`, `version`, and `project`) will raise a `DuplicateDatasetError`. You can control this behavior with additional parameters:

```python
from catalog_client import DuplicateDatasetError

# Default behavior - raise error on duplicate
try:
    dataset_id = client.register(request)
except DuplicateDatasetError as e:
    print(f"Dataset already exists: {e}")

# Update existing dataset if found
dataset_id = client.register(
    request,
    update_if_exists=True,
    error_on_duplicate=False
)

# Skip duplicates silently and return existing dataset ID
dataset_id = client.register(request, error_on_duplicate=False)
```

**Parameters:**
- `update_if_exists: bool = False` – Update the existing dataset if found
- `error_on_duplicate: bool = True` – Raise `DuplicateDatasetError` if duplicate found

Note: `update_if_exists=True` and `error_on_duplicate=True` cannot be used together.

### List datasets

```python
from catalog_client import DatasetModality

page = client.datasets.list(
    canonical_id="my-rna-seq-dataset",  # exact match filter
    version="1.0.0",                    # exact match filter
    modality=DatasetModality.sequencing,
    project="atlas",
    access_scope="public",              # filter by governance access scope
    is_latest=True,
    exclude_tombstoned=True,            # set False to include tombstoned records
    include_lineage=False,
    include_collections=False,
    offset=0,
    limit=100,
)

print(f"{page.total} total results")
for ds in page.results:
    print(ds.id, ds.name, ds.version)
```

### Search datasets

Full-text and faceted search over the active index. Returns lightweight hits; fetch
the full record with `datasets.get(id)`.

```python
results = client.datasets.search(
    q="rna-seq liver",
    modality=DatasetModality.sequencing,
    organism="Homo sapiens",
    facets=["modality", "project"],            # repeatable; returns bucket counts
    sort=DatasetSortOption.relevance,          # relevance | alphabetical | last_modified | newest | oldest
    offset=0,
    limit=10,
)
for hit in results.results:
    print(hit.id, hit.name, hit.score)
if results.facets:
    for value_count in results.facets["modality"]:
        print(value_count.value, value_count.count)
```

### Dataset history

```python
from catalog_client import AuditLogEventType

history = client.datasets.history(
    "dataset-uuid",
    event_type=AuditLogEventType.updated,  # optional filter
    skip=0,
    limit=10,
)
for entry in history.results:
    print(entry.event_type, entry.actor, entry.timestamp)
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
from catalog_client import DatasetRequest

updated = client.datasets.update(
    "dataset-uuid",
    DatasetRequest(
        canonical_id="my-rna-seq-dataset",
        name="RNA-seq batch 42 (revised)",
        version="1.0.1",
        project="atlas",
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
from catalog_client import CollectionRequest, CollectionType

col = client.collections.create(CollectionRequest(
    canonical_id="my-publication-collection",
    version="1.0.0",
    name="Nature Paper 2025 datasets",
    collection_owner="data-team",
    collection_type=CollectionType.publication,
    description="All datasets used in doi:10.1234/example",
))

updated = client.collections.update(col.id, CollectionRequest(
    canonical_id="my-publication-collection",
    version="1.0.0",
    name="Nature Paper 2025 datasets(final)",
    collection_owner="data-team",
    collection_type=CollectionType.publication,
    description="All datasets used in doi:10.1234/example",
))

client.collections.delete(col.id)  # soft-delete, status 204
```

### List / get

```python
page = client.collections.list(offset=0, limit=100)
collection = client.collections.get("collection-uuid")
```

### Add / remove datasets

`add_dataset` is idempotent and returns the updated `CollectionResponse`. `remove_dataset`
returns `None` (the API responds 204 No Content).

```python
col = client.collections.add_dataset(collection_id, dataset_id)
client.collections.remove_dataset(collection_id, dataset_id)  # returns None
```

### Child collections

Collections can nest. `add_collection` returns the updated parent; `remove_collection`
returns `None`.

```python
client.collections.add_collection(parent_id, child_id)
client.collections.remove_collection(parent_id, child_id)  # returns None
```

### List entries / parents

```python
from catalog_client import CollectionChildType

# Children (datasets and/or sub-collections); filter by entry_type
entries = client.collections.list_entries(
    collection_id, entry_type=CollectionChildType.dataset, offset=0, limit=100
)
for e in entries.results:
    print(e.entry_type, e.entry.id)

# Parent collections
parents = client.collections.list_parents(collection_id, offset=0, limit=100)
```

---

## Lineage

Lineage edges are directed relationships between two datasets. There is no update
operation — use DELETE to tombstone an edge recorded in error and create a new one.

### Edge types

| `LineageType`       | Meaning                                                  |
|---------------------|----------------------------------------------------------|
| `version_of`        | Destination is a newer version of source                 |
| `transformed_from`  | Destination was derived by processing source             |
| `copy_of`           | Destination is a copy of source (e.g. migrated location) |

### Create an edge

```python
from catalog_client import LineageEdgeRequest, LineageType

edge = client.lineages.create(LineageEdgeRequest(
    source_dataset_id="source-uuid",
    destination_dataset_id="derived-uuid",
    lineage_type=LineageType.transformed_from,
    metadata={"pipeline": "nf-core/rnaseq"},  # optional edge metadata
))
print(edge.id)
```

Lineage edges created during registration can also carry metadata via
`builder.with_lineage(source, lineage_type=…, metadata={…})`.

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

## Checksum Generation

> **Alpha feature:** The checksum generation utilities are experimental and subject to change. APIs and behavior may evolve in future releases without a deprecation cycle.

The client provides utilities to automatically generate checksums for dataset assets on supported storage platforms.

### Basic usage

```python
from catalog_client import DataAssetRequest, AssetType, StoragePlatform, DatasetRequest, DatasetModality, GovernanceMetadata, DatasetMetadata
from catalog_client.utils.checksums import generate_for_assets

# Create assets without checksums
assets = [
    DataAssetRequest(
        location_uri="s3://my-bucket/file1.txt",
        asset_type=AssetType.file,
        storage_platform=StoragePlatform.s3,
    ),
    DataAssetRequest(
        location_uri="/sf_hpc/shared/data/file2.txt",
        asset_type=AssetType.file,
        storage_platform=StoragePlatform.sf_hpc,
    ),
]

# Generate checksums
assets_with_checksums = generate_for_assets(assets)

# Use in dataset creation
dataset = client.datasets.create(DatasetRequest(
    canonical_id="my-dataset",
    name="My Dataset",
    version="1.0.0",
    project="atlas",
    modality=DatasetModality.sequencing,
    locations=assets_with_checksums,  # Now includes checksums
    governance=GovernanceMetadata(...),
    metadata=DatasetMetadata(),
))
```

### Algorithm selection

```python
# Specify algorithm (default: blake3, except S3 prefers existing CRC32)
assets_with_checksums = generate_for_assets(assets, algorithm="blake2b")

# Supported algorithms: 'blake3', 'blake2b', 'blake2s', 'crc32'
```

### S3 optimization control

```python
# Default: use existing S3 checksums when available, compute otherwise
assets_with_checksums = generate_for_assets(assets, compute_if_no_s3_checksum=True)

# Only use existing S3 checksums, skip assets without them
assets_with_checksums = generate_for_assets(assets, compute_if_no_s3_checksum=False)
```

### How a platform is chosen

For each asset the platform is resolved in two steps:

1. **Explicit `storage_platform`** — if set, it is used directly. Any value is supported
   for checksumming **except** `external` and `other`, which are skipped.
2. **URI fallback** — if `storage_platform` is not set, only S3 is auto-detected (URI
   starting with `s3://` or `s3a://`); anything else is skipped.

Always set `storage_platform` explicitly on filesystem assets (`sf_hpc`, `chi_hpc`,
`ny_hpc`, `reef`, `kelp`) — the URI fallback only recognizes S3.

### How a checksum is computed

| Platform | How it's computed | Notes |
|----------|-------------------|-------|
| **S3** (`s3`) | Reuses an existing S3 checksum when available, otherwise downloads the object | Prefers existing CRC32 when `algorithm=None` |
| **Filesystem** (`sf_hpc`, `chi_hpc`, `ny_hpc`, `reef`, `kelp`) | Reads the file at `location_uri` and hashes it | Local filesystem access required; defaults to `blake3` |
| **`external`, `other`** | Not computed | Skipped with a warning |

**Current limitations:**
- Only `AssetType.file` assets are supported. Folder assets (`AssetType.folder`) are skipped.
- Assets on unsupported platforms (`external`, `other`) or paths without an explicit `storage_platform` that aren't S3 URIs are skipped with warnings.

### Error handling

```python
import warnings
from catalog_client.utils.checksums import ChecksumWarning

# Capture checksum warnings
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    assets_with_checksums = generate_for_assets(assets)

    for warning in w:
        if issubclass(warning.category, ChecksumWarning):
            print(f"Checksum warning: {warning.message}")
```

Common warnings:
- Unsupported storage platform
- File not found or access denied
- Algorithm not available (e.g., `blake3` package not installed)

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
    CatalogHTTPError,
    CatalogServerError,
    CatalogConnectionError,
    CatalogError,
    DuplicateDatasetError,
    LineageResolutionError,
    NotFoundError,
    ValidationError,
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
except CatalogHTTPError as e:
    print(f"Unexpected HTTP error {e.status_code}: {e.detail}")
except CatalogConnectionError as e:
    print(f"Network error: {e}")
except CatalogError as e:
    print(f"Unexpected catalog error: {e}")

# For dataset registration
try:
    dataset_id = client.register(request)
except DuplicateDatasetError as e:
    print(f"Dataset already exists: {e}")
    # Consider using update_if_exists=True or error_on_duplicate=False
except LineageResolutionError as e:
    print(f"Could not resolve source dataset ref: {e}")
```

---

## Key models reference

| Model                          | Used for                                                               |
|--------------------------------|------------------------------------------------------------------------|
| `DatasetRequest`               | Creating or updating a dataset                                         |
| `DatasetCreate`                | **Deprecated** — alias for `DatasetRequest`, will be removed           |
| `DatasetResponse`              | Return value from create / update                                      |
| `DatasetWithRelationsResponse` | Return value from get / list (includes optional lineage + collections) |
| `DataAssetRequest`             | Asset entry inside `DatasetRequest.locations`                          |
| `DataAssetResponse`            | Asset entry inside response `locations`                                |
| `GovernanceMetadata`           | Access control and ownership info                                      |
| `DatasetMetadata`              | Top-level metadata envelope (`experiment`, `sample`, `data_summary`)   |
| `SampleMetadata`               | Biological sample information                                          |
| `ExperimentMetadata`           | Experimental setup and instrument info                                 |
| `DataSummaryMetadata`          | Content descriptors and modality-specific measurements                 |
| `DataQualityChecks`            | QC pass / fail / skipped check names                                   |
| `OntologyEntry`                | `{ label, ontology_id }` — organism, disease, development stage        |
| `TissueEntry`                  | Extends `OntologyEntry` with optional `type` field                     |
| `CollectionRequest`            | Creating/Updating a collection                                         |
| `CollectionResponse`           | Collection return value                                                |
| `LineageEdgeRequest`           | Creating a lineage edge                                                |
| `LineageEdgeResponse`          | Lineage edge return value                                              |
| `RegistrationRequest`          | Full registration payload (built via `new_registration()` builder)     |
| `PaginatedResponse[T]`         | Wrapper for list endpoints (`total`, `limit`, `offset`, `results`)     |

### Enums

| Enum | Values |
|---|---|
| `DatasetModality` | `imaging`, `sequencing`, `mass_spec`, `unknown` |
| `DatasetType` | `raw`, `processed` |
| `AssetType` | `file`, `folder` |
| `StoragePlatform` | `s3`, `sf_hpc`, `chi_hpc`, `ny_hpc`, `reef`, `kelp`, `external`, `other` |
| `LineageType` | `version_of`, `transformed_from`, `copy_of` |
| `CollectionType` | `publication`, `training` |
