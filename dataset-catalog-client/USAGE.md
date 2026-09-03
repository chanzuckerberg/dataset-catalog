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

## Command-line interface

Installing the package also installs a read-only `catalog` command for querying
the catalog from the shell. It only issues GET requests — creating, updating,
and deleting always go through the Python API. One subcommand, `checksum`, does
not talk to the catalog at all; see [Checksums from the command
line](#checksums-from-the-command-line).

Configure the query subcommands via the environment:

```bash
export CATALOG_API_URL=https://your-catalog.example.com
export CATALOG_API_TOKEN=your-token-here
```

Each subcommand prints a human-readable **table** when stdout is a terminal and
**JSON** when the output is piped or redirected — so interactive use is readable
and `... | jq` still works unchanged. Force either format with `-o/--output
table|json`.

```bash
# Full-text + faceted search (lightweight hits; latest versions only by default)
catalog search --q "brightfield" --organism "Homo sapiens" --limit 5

# Discover the actual filter vocabulary before filtering (value + count per field)
catalog facets --fields organism,tissue,assay,project

# One full record, by UUID or by coordinates
catalog get 6f9d1c2e-...-uuid --lineage --collections
catalog get my-dataset --version 1.0.0 --project atlas

# Exact-coordinate listing (compact summaries; --full for complete records)
catalog list --project atlas --canonical-id my-dataset --all-versions

# Walk provenance up (ancestors), down (derived datasets), or both
catalog lineage 6f9d1c2e-...-uuid --direction up --depth 3

# Browse collections
catalog collections list
catalog collections entries <collection-uuid>
catalog collections parents <collection-uuid>

# Hash a local path or S3 URI — no catalog credentials involved
catalog checksum data/sample.h5ad
```

Useful flags:

- `-o/--output` (all subcommands) — `table` or `json`; defaults to `table` on a terminal, `json` when piped.
- `--all-versions` (`search`, `list`, `facets`) — include superseded versions; by default only `is_latest` records are returned.
- `--cursor` (`search`, `list`) — the `next_cursor` from a previous page; constant-cost at any depth. Required past `--offset 10000` on `list`, and the only way to page `search`.
- `--offset` (`list` only) — skip N records, max 10000; deeper paging exits with code 2 and directs you to `--cursor`.
- `--sort` (`search`) — `relevance`, `alphabetical`, `last_modified`, `newest`, `oldest`. Defaults to `relevance` when `--q` is given, `last_modified` otherwise. This default is applied by the CLI only; the Python `datasets.search()` omits `sort` unless you pass one, leaving the choice to the server.
- `--sort` (`list`) — `last_modified`, `newest`, `oldest` only; the list route has no relevance score and no alphabetical order. Unset leaves the choice to the server. Prefer `newest`/`oldest` for a `--cursor` walk: they sort on the immutable `created_at`, whereas `last_modified` can shift mid-walk and skip or repeat a record.
- `--facets` (`search`) — request bucket counts alongside hits, e.g. `--facets organism,tissue`.
- `--type` (`lineage`) — restrict the walk to one edge type (`version_of`, `transformed_from`, `copy_of`).

Example `facets` output (`-o json`):

```json
{
  "total": 42,
  "facets": {
    "organism": [
      { "value": "Homo sapiens", "count": 30 },
      { "value": "Mus musculus", "count": 12 }
    ]
  }
}
```

On failure the command prints `error: <message>` to stderr and exits with a
code you can branch on in scripts:

| Code | Meaning |
|------|---------|
| `0`  | success |
| `1`  | other client error |
| `2`  | usage / configuration error (bad flags, missing env vars) |
| `3`  | authentication error (401 — check `CATALOG_API_TOKEN`) |
| `4`  | not found (404) |
| `5`  | server or connection error (5xx / network) |

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
from catalog_client import DatasetListSortOption, DatasetModality

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
    sort=DatasetListSortOption.last_modified,  # optional; omit to use the server default
    offset=0,                           # shallow paging only, max 10000
    limit=100,                          # 1-500, enforced client-side
    include_total=True,                 # False skips the count query
)

print(f"{page.total} total results")
for ds in page.results:
    print(ds.id, ds.name, ds.version)
```

Returns a `CursorPaginatedResponse`. `total` is `None` when
`include_total=False`, and `offset` is `None` when paging by cursor.

### Paginating datasets

The list route pages either by `offset` or by keyset `cursor` — passing both
raises `CatalogUsageError`. Offset paging is fine for the first few pages, but
its cost grows with depth and the server must walk and discard every skipped
row, so **`offset` above 10,000 raises `CatalogUsageError`** and points you at
the cursor. Past a few thousand records, follow `next_cursor` instead:

```python
cursor = None
while True:
    page = client.datasets.list(project="atlas", cursor=cursor, limit=500,
                                include_total=False)
    for ds in page.results:
        print(ds.id)
    if page.next_cursor is None:
        break
    cursor = page.next_cursor
```

`iter_all()` does that walk for you:

```python
for ds in client.datasets.iter_all(project="atlas", limit=500):
    print(ds.id, ds.name)
```

`sort` is omitted unless you pass one, so the server default applies — and
that default sorts on a mutable key, meaning a row modified mid-walk can be
skipped or repeated. For a walk that cannot miss or duplicate rows, sort on
the immutable `created_at`:

```python
for ds in client.datasets.iter_all(sort=DatasetListSortOption.newest, limit=500):
    print(ds.id, ds.name)
```

A cursor is only valid for the `sort` and filters it was issued with —
changing either mid-walk raises `RecordValidationError` (422).

`iter_all()` and `iter_search()` stop rather than loop if the server hands
back a cursor it already issued, or promises another page while returning an
empty one. Either would otherwise be an unbounded request loop; both raise
`CatalogError`, since they are server faults rather than caller mistakes.

### Search datasets

Full-text and faceted search over the active index. Returns lightweight hits;
fetch the full record with `datasets.get(id)`, or pass `hydrate=True` below.

```python
results = client.datasets.search(
    q="rna-seq liver",
    modality=DatasetModality.sequencing,
    organism="Homo sapiens",
    cohort="cohort-a",                         # from metadata.experiment.cohort
    file_format="fastq",                       # matches a dataset location
    storage_platform="s3",                     # matches a dataset location
    facets=["modality", "project"],            # repeatable; returns bucket counts
    fields=["license", "cell_count"],          # extra fields on each hit
    sort=DatasetSortOption.relevance,          # optional; omit to use the server default
    limit=10,                                  # 1-1000 (1-100 with hydrate=True), enforced client-side
)
for hit in results.results:
    print(hit.id, hit.name, hit.score)
    print(hit.model_extra)                     # fields requested via fields=
if results.facets:
    for value_count in results.facets["modality"]:
        print(value_count.value, value_count.count)
```

Pass `hydrate=True` to get full `DatasetResponse` records instead of hits,
at the cost of one extra query per page:

```python
results = client.datasets.search(q="rna-seq liver", hydrate=True, limit=100)
for record in results.results:
    print(record.id, record.metadata)
```

**Search pages by cursor only** — it has no `offset` parameter. Follow
`next_cursor` until it comes back `None`, or let `iter_search()` walk it:

```python
for hit in client.datasets.iter_search(q="rna-seq liver", limit=1000):
    print(hit.id, hit.name)
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

The `checksum` extra adds `blake3`, `crcmod`, and `awscrt`:

```bash
uv pip install 'catalog-client[checksum] @ git+https://github.com/chanzuckerberg/dataset-catalog.git#subdirectory=dataset-catalog-client'
```

It is optional — without it, `blake2b` and `crc32` still work from the standard library,
and the default algorithm falls back to `blake2b`.

Checksums are content-addressed: the same bytes produce the same digest regardless of
path, storage backend, or whether the file was hashed on its own or as part of a folder.

`for_assets` also fills in each asset's `size_bytes`. The size is read from storage
metadata (`os.fstat`, S3 `ContentLength`, S3 listing sizes) rather than counted while
hashing, so it costs no extra I/O and is reported even when a stored S3 checksum means the
object is never downloaded. A `size_bytes` you supplied yourself is never overwritten.

See [docs/checksum_guide.md](docs/checksum_guide.md) for the full reference, including
the reproducibility guarantees, Merkle-tree folder hashing, S3 multipart semantics, and
migration from `catalog_client.utils.checksums`.

### Basic usage

```python
import boto3
from catalog_client import DataAssetRequest, AssetType, StoragePlatform, DatasetRequest, DatasetModality, GovernanceMetadata, DatasetMetadata
from catalog_client.utils.checksum import for_assets

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

# Generate checksums and sizes — returns copies; `assets` is left untouched
assets_with_checksums = for_assets(assets, s3_client=boto3.client("s3"))

# Use in dataset creation
dataset = client.datasets.create(DatasetRequest(
    canonical_id="my-dataset",
    name="My Dataset",
    version="1.0.0",
    project="atlas",
    modality=DatasetModality.sequencing,
    locations=assets_with_checksums,  # Now includes checksums and sizes
    governance=GovernanceMetadata(...),
    metadata=DatasetMetadata(),
))
```

### Algorithm selection

```python
from catalog_client.utils.checksum import Algorithm

# Specify an algorithm. With algorithm=None (the default), S3 assets reuse an
# existing stored checksum, and anything else uses default_algorithm().
assets_with_checksums = for_assets(assets, algorithm=Algorithm.blake2b, s3_client=boto3.client("s3"))
```

| Algorithm | Extra dependency |
|---|---|
| `Algorithm.blake3` | `blake3` |
| `Algorithm.crc64` | `crcmod` (CRC-64/ECMA-182) |
| `Algorithm.crc64nvme` | `awscrt` |
| `Algorithm.crc32`, `Algorithm.blake2b` | none (stdlib) |

Requesting an algorithm whose dependency is not installed raises `ImportError`.
`default_algorithm()` never does: it returns `blake3` when installed and `blake2b`
otherwise.

### S3 optimization control

```python
# Default: use existing S3 checksums when available, compute otherwise
assets_with_checksums = for_assets(assets, compute_if_no_s3_checksum=True, s3_client=boto3.client("s3"))

# Only use existing S3 checksums, skip assets without them
assets_with_checksums = for_assets(assets, compute_if_no_s3_checksum=False, s3_client=boto3.client("s3"))
```

The flag controls **downloads**, so it does not block a folder whose children all carry a
stored checksum — assembling that needs no download. `for_location` takes the same
parameter with the same default.

### How a platform is chosen

`storage_platform` is required on `DataAssetRequest`, so the platform is always taken
directly from the asset. Every platform is supported for checksumming **except**
`external` and `other`, which are skipped with a `ChecksumWarning`.

`DataAssetResponse` widens `storage_platform` to optional so that legacy assets parse;
an asset with no platform is likewise skipped with a warning.

### How a checksum is computed

| Platform | How it's computed | Notes |
|----------|-------------------|-------|
| **S3** (`s3`) | Reuses a stored S3 checksum when available, otherwise downloads the object | Prefers an existing stored checksum when `algorithm=None`; multipart composite values are ignored |
| **Filesystem** (`sf_hpc`, `chi_hpc`, `ny_hpc`, `reef`, `kelp`) | Reads the file at `location_uri` and hashes it | Local filesystem access required; defaults to `default_algorithm()` |
| **`external`, `other`** | Not computed | Skipped with a warning |

Both `AssetType.file` and `AssetType.folder` are supported. Folders are hashed by
combining per-file digests into a Merkle root; a file's digest is identical whether it is
hashed on its own or as a folder child — see
[docs/checksum_guide.md](docs/checksum_guide.md) for details.

### Error handling

```python
import warnings
from catalog_client.utils.checksum import ChecksumWarning

# Capture checksum warnings
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    assets_with_checksums = for_assets(assets, s3_client=boto3.client("s3"))

    for warning in w:
        if issubclass(warning.category, ChecksumWarning):
            print(f"Checksum warning: {warning.message}")
```

Common warnings:
- Unsupported or missing storage platform
- Empty `location_uri`, or no `s3_client` supplied for an S3 asset
- File not found or access denied
- Algorithm not available (e.g., `blake3` requested but the package is not installed)

Every skip and failure is reported this way, so `warnings.simplefilter("error", ChecksumWarning)`
turns all of them into exceptions.

### Checksums from the command line

`catalog checksum PATH` hashes one local path or S3 URI. It contacts no catalog
API and needs no `CATALOG_API_URL`/`CATALOG_API_TOKEN`; `s3://` paths use the
ambient AWS credentials.

```bash
# Local file — blake3 if the `checksum` extra is installed, else blake2b
catalog checksum data/sample.h5ad

# Local directory: one digest for the whole tree
catalog checksum data/run-01/

# ...and one row per descendant
catalog checksum data/run-01/ --children -o table

# Pick the algorithm explicitly
catalog checksum data/sample.h5ad --algorithm crc32

# S3 object: reuses a checksum already stored on the object when --algorithm is
# omitted, so nothing is downloaded
catalog checksum s3://my-bucket/prefix/object.tif

# Integrity audit: ignore what S3 stored and hash the bytes
catalog checksum s3://my-bucket/prefix/object.tif --algorithm crc32 --recompute
```

```
DIGEST                            ALG     SIZE     SOURCE     KIND  PATH
--------------------------------  ------  -------  ---------  ----  ------------------
9f2a...                           crc32   1048576  s3_native  file  s3://my-bucket/...
```

`SOURCE` says where the digest came from: `computed` (bytes were hashed),
`s3_native` (S3's own CRC32/CRC64NVME), or `s3_metadata` (an
`x-checksum-<algo>` value written by a previous run).

Flags:

- `--algorithm` — `blake3`, `blake2b`, `crc32`, `crc64`, `crc64nvme`. Omit it to
  reuse whatever is stored on the S3 object, falling back to `blake3`/`blake2b`.
- `--recompute` — ignore stored S3 checksums and hash the bytes. No effect on local paths.
- `--folder` / `--file` — treat an S3 key as a prefix or a single object instead of
  inferring from a trailing `/`. Local paths are always classified by `os.path.isdir`.
- `--children` — list every descendant of a folder, not just its total.
- `--workers N` — threads to use for a folder. Defaults to a value chosen from the
  available CPUs; `1` forces serial. Never changes the checksum.
- `-o json` — the full `ChecksumResult`: `chunks`, `children`, `merkle_root`,
  `content_digest`, and the base64 forms S3 headers expect (`s3_base64`, plus
  `s3_composite_base64` for files).

Exit codes follow the table above: `2` for a bad flag, a malformed `s3://` URI, or a
missing optional dependency; `4` for a path or S3 key that does not exist; `5` for an
S3 request failure such as missing credentials.

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
    CatalogUsageError,
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
except CatalogUsageError as e:
    # Bad arguments the client rejects without a round trip: offset past
    # 10,000, cursor together with offset, a page size over the route's
    # ceiling. Also a ValueError, so existing `except ValueError` still works.
    print(f"Bad arguments: {e}")
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
| `PaginatedResponse[T]`         | Wrapper for collection/lineage/history lists (`total`, `limit`, `offset`, `results`) |
| `CursorPaginatedResponse[T]`   | Wrapper for `datasets.list()` — adds `next_cursor`; `total` and `offset` are nullable |
| `DatasetSearchResponse[T]`     | `datasets.search()` result — `total` (nullable), `limit`, `next_cursor`, `results`, `facets` (no `offset`). Generic over the hit type, so `hydrate` is validated rather than guessed |
| `DatasetSearchPage`            | What `search()` returns: `DatasetSearchResponse[DatasetResponse]` when `hydrate=True`, `DatasetSearchResponse[DatasetSearchHit]` otherwise |
| `DatasetSearchHit`             | Lightweight search hit; extra `fields=` land in `model_extra`          |

### Enums

| Enum | Values |
|---|---|
| `DatasetModality` | `imaging`, `sequencing`, `mass_spec`, `unknown` |
| `DatasetType` | `raw`, `processed` |
| `AssetType` | `file`, `folder` |
| `StoragePlatform` | `s3`, `sf_hpc`, `chi_hpc`, `ny_hpc`, `reef`, `kelp`, `external`, `other` |
| `LineageType` | `version_of`, `transformed_from`, `copy_of` |
| `CollectionType` | `publication`, `training` |
| `DatasetSortOption` | `relevance`, `alphabetical`, `last_modified`, `newest`, `oldest` — `datasets.search()`; unset omits the param |
| `DatasetListSortOption` | `last_modified`, `newest`, `oldest` — `datasets.list()`; unset omits the param |
