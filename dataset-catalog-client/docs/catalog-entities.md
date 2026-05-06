# Catalog Entities

The Scientific Dataset Catalog is built around four core entities: **Dataset**, **Data Asset**, **Collection**, and **Lineage**. Understanding how they relate to each other is the foundation for using the catalog effectively.

## Contents

- [Dataset](#dataset)
- [Data Asset](#data-asset)
- [Collection](#collection)
- [Lineage](#lineage)
- [How the entities relate](#how-the-entities-relate)

---

## Dataset

A dataset is the primary unit of the catalog. It represents a discrete scientific data product — a collection of files or folders produced at a specific point in a research workflow.

### Identity

Every dataset is uniquely identified by three fields that together form its *signature*:

| Field | Description |
|---|---|
| `canonical_id` | A stable external identifier you assign (e.g. `rna-seq-batch-42`). |
| `version` | A version string (e.g. `1.0.0`). Defaults to `"1.0.0"` if omitted. |
| `project` | The project the dataset belongs to (e.g. `atlas`). |

These three fields are *immutable* in the sense that changing any one of them tombstones the existing record and creates a new one. This makes the signature a reliable pointer even across updates.

### What a dataset captures

Beyond identity, a dataset record stores:

- **Display information** — `name`, `description`, a `modality` (imaging / sequencing / mass spec / unknown), and a `dataset_type` (raw or processed).
- **Physical locations** — one or more `DataAsset` entries pointing to where the data actually lives on storage.
- **Governance** — ownership, access scope, sensitivity, and embargo information.
- **Scientific metadata** — experiment setup, sample biology, and data summary statistics.
- **Quality information** — optional pass/fail/skipped quality check results.

### Versioning

The `is_latest` flag marks whether a dataset record is the most recent version. When you register a new version of an existing dataset, set `is_latest=True` on the new record. The catalog does not automatically flip the flag on older records — that is the responsibility of the registering system.

Updating `canonical_id`, `version`, or `project` triggers a tombstone-and-replace: the old record is soft-deleted and a new one is created with a new UUID. All other fields can be patched in place.

---

## Data Asset

A data asset is a physical file or folder that backs a dataset. Every dataset must have at least one asset; many have several (e.g. a processed output alongside a manifest or index file).

### Key properties

| Property | Description |
|---|---|
| `location_uri` | The storage path, e.g. `s3://my-bucket/data/` or `/hpc/shared/data/file.h5ad`. |
| `asset_type` | `file` or `folder`. |
| `storage_platform` | Where the asset lives. Auto-inferred from the URI if not provided. |
| `encoding` | File encoding, e.g. `zarr`, `h5ad`, `tiff`. |
| `file_format` | File format, e.g. `parquet`, `tiff`, `fastq`. |
| `size_bytes` | Size of the file or folder in bytes. |
| `checksum` / `checksum_alg` | Integrity hash and the algorithm used (e.g. `blake3`, `md5`, `sha256`). |
| `file_count` | Number of files inside a folder asset. |

### Signature fields

The following asset fields are *signature fields* — changing them produces a new asset record:

- `location_uri`
- `asset_type`
- `size_bytes`
- `checksum`
- `checksum_alg`

### Storage platforms

The `storage_platform` is auto-inferred from the URI:

| Platform   | URI pattern |
|------------|---|
| `s3`       | Starts with `s3://` or `s3a://` |
| `hpc`      | Contains `/hpc/` |
| `sf_hpc`   | Explicitly set |
| `chi_hpc`  | Explicitly set |
| `ny_hpc`   | Explicitly set |
| `reef`     | Explicitly set |
| `kelp`     | Explicitly set |
| `external` | Explicitly set |
| `other`    | Explicitly set or unrecognized |

### Checksum generation

The catalog client includes a utility to compute checksums automatically before registration:

```python
from catalog_client.utils.checksums import generate_for_assets

assets_with_checksums = generate_for_assets(assets)
```

Only `file` assets on supported platforms (S3, HPC, CoreWeave) are processed. Folder assets and unsupported platforms are skipped with a warning. This requires the caller to have permission to access those files, at the time of calling the method.

### Tracking changes and detecting drift

`checksum` and `checksum_alg` are optional fields, but populating them at registration time is strongly recommended. A checksum is the only reliable signal that the bytes on storage still match what was originally cataloged. Without it, the catalog records *where* the data lives but cannot verify *what* it contains.

**Why drift happens**

- Files on HPC or object storage can be silently overwritten or corrupted.
- Pipeline re-runs may write to the same path, replacing the original data.
- Copy or migration jobs may produce truncated or bit-rotted outputs.
- Manual edits to "fix" a file go unnoticed if there is no reference hash.

**How the catalog surfaces a change**

Because `checksum` and `checksum_alg` are [signature fields](#signature-fields), they participate in asset identity. Registering an asset with a different checksum does not silently overwrite the old record — it creates a new asset record and tombstones the previous one, giving you a permanent audit trail of what hash was recorded at each point in time.

**Drift detection workflow**

1. At registration, always include a checksum using `generate_for_assets()`.
2. At verification time (e.g. before a training run or after a migration), recompute checksums from storage and compare them against the values stored in the catalog.
3. If drift is confirmed, register a new dataset version with the updated assets and record a lineage edge (`version_of` or `copy_of`) back to the original.

**Algorithm guidance**

| Algorithm | Use when |
|---|---|
| `blake3` | Default for HPC/filesystem assets. Fast and cryptographically strong. Requires the `blake3` package. |
| `blake2b` | Good alternative when `blake3` is unavailable. No extra dependency. |
| `crc32` | Fast, low-overhead. Suitable for detecting accidental corruption, not adversarial changes. |
| S3 CRC32 | Used automatically for S3 objects that already have a stored CRC32 checksum, avoiding a full download. |

All algorithms produce a hex string stored in `checksum`. The algorithm name is stored in `checksum_alg` so comparisons always use the correct function.

---

## Collection

A collection is a named, mutable grouping of datasets. Collections exist to bundle related datasets together for a specific purpose — a publication, a model-training run, a project snapshot — without duplicating or moving the underlying data.

### Key properties

| Property | Description |
|---|---|
| `canonical_id` | Stable external identifier for the collection. |
| `version` | Version of the collection (e.g. `1.0.0`). |
| `name` | Human-readable display name. |
| `collection_type` | `publication` or `training`. |
| `collection_owner` | Team or person responsible for the collection. |
| `description` | Free-text description of the collection's purpose. |

### Membership

Collections are flat: they hold dataset references but impose no hierarchy or ordering. Datasets can belong to multiple collections simultaneously.

Membership is managed with idempotent operations of add and remove.

### Mutability

Collections are mutable: name, description, and membership can all be updated after creation. The `canonical_id` and `version` together form the collection's identity — changing them follows the same tombstone-and-replace behavior as datasets.

---

## Lineage

Lineage captures directed relationships between datasets. A lineage *edge* records that one dataset was derived from, is a newer version of, or is a copy of another.

### Edge structure

Each edge connects two datasets:

| Field | Description |
|---|---|
| `source_dataset_id` | The upstream (input) dataset UUID. |
| `destination_dataset_id` | The downstream (output) dataset UUID. |
| `lineage_type` | The nature of the relationship (see below). |

### Edge types

| Type | Meaning |
|---|---|
| `version_of` | Destination is a newer version of source — same content, incremented version. |
| `transformed_from` | Destination was derived by processing source, e.g. raw FASTQ → aligned BAM → count matrix. |
| `copy_of` | Destination is a copy of source at a different storage location, e.g. after a migration. |

### Immutability

Lineage edges are **immutable** once created. This is intentional: lineage is an audit trail, not a mutable property. To correct a mistaken edge, soft-delete it and record the correct one.

### Recording lineage

Lineage can be recorded at dataset registration time using the builder or recorded independently after datasets already exist.

### Traversal

Lineage edges can be queried by source or destination dataset. When fetching a dataset with `include_lineage=True`, the response includes `incoming_lineage` and `outgoing_lineage` edge lists:

```python
dataset = client.datasets.get("dataset-uuid", include_lineage=True)
print(dataset.incoming_lineage)   # edges pointing to this dataset
print(dataset.outgoing_lineage)   # edges originating from this dataset
```

---

## How the entities relate

```
Collection
└── contains (many-to-many) ──► Dataset
                                  ├── has (one-to-many) ──► DataAsset
                                  │                          (files/folders on storage)
                                  │
                                  └── connected by ──► LineageEdge ──► Dataset
                                                        (transformed_from /
                                                         version_of / copy_of)
```

A dataset always has at least one data asset and exactly one governance block. Collections and lineage edges are optional — a dataset can exist without belonging to any collection and without any lineage edges.
