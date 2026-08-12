# Scientific Dataset Catalog — Schema & Definitions (v1.5.0)

> **Draft — unreleased.** This document specifies v1.5.0 ahead of the code landing.
> The Python client still defaults `record_schema_version` to `v1.4.0`; until the
> implementation ships, [`v1.4.0/schema.md`](../v1.4.0/schema.md) remains the version
> in force for new registrations. See [`../CHANGELOG.md`](../CHANGELOG.md) for what
> changes between versions.

## Purpose

This document defines the shared vocabulary for the Dataset Catalog. It is the
authoritative, field-level reference for anyone designing, building, or consuming
the catalog API. It describes *what* the catalog records, not *how* any particular
client library is used.

The catalog is built around four core entities: **Data Asset**, **Dataset**,
**Collection**, and **Lineage Edge**. Each section below covers what the entity is,
how it behaves when updated, and the fields it carries.

## Contents

- [Definitions](#definitions)
- [Entities overview](#entities-overview)
- [Data Asset](#data-asset)
- [Dataset](#dataset)
- [Lineage Edge](#lineage-edge)
- [Collection](#collection)
- [How the entities relate](#how-the-entities-relate)
- [API models](#api-models)

---

## Definitions

| Term | Meaning |
|---|---|
| **Required** | Enforced by the schema — validation fails without it. |
| **Recommended** | Not enforced, but strongly encouraged for catalog quality. |
| **Optional** | Include when applicable. |
| **Deprecated** | Still accepted for backward compatibility; do not populate on new records. |
| **Signature field** | A field that participates in the record's identity. Changing it does not patch in place — see *Tombstone*. |

New in v1.5.0: field tables carry a **Level** column (`Required` / `Recommended` /
`Optional` / `Deprecated`) rather than a boolean *Required* column. `Recommended`
captures fields that validation permits to be absent but that the catalog expects for a
usable record.

---

## Entities overview

| Entity | Role |
|---|---|
| **Data Asset** | A single file or folder tracked as an atomic unit of data. |
| **Dataset** | A named, versioned container for one or more Data Assets. |
| **Collection** | An organizational grouping of datasets, structured as a multi-level provenance hierarchy. |
| **Lineage Edge** | A directed relationship between two datasets recording provenance. |

---

## Data Asset

A Data Asset is a single file or folder. It can represent a pipeline output, a raw
instrument capture, or an external reference such as a reference genome hosted by a
third party. It is the smallest unit of data the catalog tracks.

Every Data Asset belongs to exactly one Dataset and cannot exist on its own.

### File vs. folder assets

Assets can be individual files (e.g. a single H5AD) or folders (e.g. a Zarr store).

### Integrity verification

For single-file assets, the `checksum` is a standard hash of the file contents
(MD5, SHA-256, etc.). For folder assets, the checksum is computed Merkle-style:
individual file checksums are sorted deterministically and hashed together. This
means all files must be enumerated at registration time, but it gives a reliable
integrity guarantee over the entire folder.

Populating `checksum` and `checksum_alg` at registration time is strongly recommended:
a checksum is the only reliable signal that the bytes on storage still match what was
originally cataloged. Because these are signature fields, registering an asset with a
different checksum creates a new asset record and tombstones the previous one, giving
a permanent audit trail of what hash was recorded at each point in time.

### Signature fields

The following five fields form the asset's signature. Changing any of them from a
*non-null* value to a different value tombstones the existing record and creates a new
one. If a field is currently `null`, it can be filled in without triggering a
tombstone, since that is just adding previously missing information.

- `location_uri`
- `asset_type`
- `size_bytes`
- `checksum`
- `checksum_alg`

Note that this is *looser* than the [Dataset signature rules](#signature-fields-1),
where filling a null signature field also tombstones the record.

### Properties

| Field | Type | Level | Description |
|---|---|---|---|
| `storage_platform` | string | Required | Storage backend. Valid values: `s3`, `sf_hpc`, `chi_hpc`, `ny_hpc`, `reef`, `kelp`, `globus`, `external`, `other`. |
| `location_uri` | string | Required | Full URI with storage scheme (e.g. `s3://`, `gs://`, `https://`, `globus://`, `file://`). |
| `asset_type` | string | Required | `file` or `folder`. |
| `size_bytes` | integer | Recommended | Total size in bytes. For folder assets, the sum of all included files. |
| `checksum` | string | Recommended | Integrity hash. Single files use a standard hash; folders use a Merkle-style hash over sorted individual file checksums. |
| `checksum_alg` | string | Recommended | Algorithm used to compute the checksum (e.g. `md5`, `sha256`, `blake3`). |
| `encoding` | string | Optional | Content encoding (e.g. `gzip`, `zstd`). |
| `file_format` | string | Optional | File format or MIME type (e.g. `parquet`, `fasta`, `json`). |
| `description` | string | Optional | Human-readable description of this specific asset. |
| `file_count` | integer | Optional | Number of files in the folder. For folder-type assets only. |

### Examples

- A single H5AD file.
- A Zarr folder containing one field of view.
- A reference genome FASTA hosted externally.

---

## Dataset

A Dataset is a named, versioned container for one or more Data Assets. Datasets are
registered at meaningful points in a scientific workflow: when data comes off an
instrument, or when processing produces a new output worth tracking. Scientific
context (what the experiment was), governance (who may access the data), and
modality-specific measurements all live at the dataset level, not on the individual
assets.

### Dataset types

`dataset_type` records how the dataset came to exist. The catalog stores it as a
*label*; the actual derivation between datasets is recorded in the
[lineage graph](#lineage-edge), not inferred from the type.

**Raw** (`dataset_type = "raw"`) datasets capture the output of a single experimental
run — one pass through an instrument or pipeline under consistent conditions (same
organism, assay, and modality). Files produced by the same run under the same
conditions belong in one dataset; if anything material differs between two groups of
files, register them as separate datasets.

**Processed** (`dataset_type = "processed"`) datasets are always *new* datasets.
Processing an existing dataset never mutates the original — the output is registered as
its own record and linked back to the dataset(s) it was derived from with a lineage
edge (typically `transformed_from`). A processed dataset may derive from multiple
upstream datasets spanning different samples, assays, or modalities.

**Aggregated** (`dataset_type = "aggregated"`, new in v1.5.0) datasets are assembled by
combining several existing datasets into a single record — for example an atlas or a
merged cohort — rather than by transforming a single upstream run. Like processed
datasets, they are new records and link back to every contributing dataset with
lineage edges.

### Enums

#### `DatasetModality`

| Value |
|---|
| `imaging` |
| `sequencing` |
| `mass spec` |
| `spatial tx` |
| `unknown` |

`spatial tx` (spatial transcriptomics) is new in v1.5.0. Use it for assays that resolve
transcript measurements in situ; pair it with an `experiment.sub_modality` (e.g.
`Visium`, `Xenium`, `MERFISH`) for the specific platform.

#### `DatasetType`

| Value |
|---|
| `raw` |
| `processed` |
| `aggregated` |

### Signature fields

The combination of `canonical_id`, `version`, and `project` uniquely identifies a
dataset:

```
canonical_id, version, project
```

Changing **any** signature field — *including filling one in from `null`* — tombstones
the existing record, sets `is_latest = false` on it, and inserts a new record with
`record_version` incremented. (This is stricter than the
[Data Asset signature rules](#signature-fields), where filling a null field is an
in-place change.)

On such a version bump the catalog also records a `version_of` lineage edge from the
old record to the new one, and carries over the old record's active lineage edges,
remapping them to the new record's assets by URI.

Whenever a new `is_latest` record is registered — on a plain create or on a version
bump — any other `is_latest` record in the same (`canonical_id`, `project`) group is
demoted to `is_latest = false`, so at most one latest version survives.

| Field | Description |
|---|---|
| `canonical_id` | Human-readable stable identifier, unique within a project. Does not change across versions. |
| `version` | Version string for the dataset. |
| `project` | The project this dataset belongs to. |

### Update behavior

- Changes to any non-signature field (`name`, `description`, `modality`, `metadata`,
  `governance`, etc.) are applied in place and bump `record_version` — but only when a
  value actually changed.
- Changes to `locations` are handled differentially: new assets are added, assets
  missing from the update are tombstoned, and existing assets follow the
  [Data Asset signature rules](#signature-fields) above. A `locations` change does not
  tombstone the whole dataset.
- Tombstoned datasets cannot be updated; an update against one returns `404`.

### Properties — core fields

| Field | Type | Level | Description |
|---|---|---|---|
| `canonical_id` | string | Required | Stable identifier across versions, unique within a project. *(signature)* |
| `version` | string | Required (default `1.0.0`) | Version of the dataset. *(signature)* |
| `project` | string | Required | The project this dataset belongs to (e.g. `CellXGene`, `CryoET`, `BCP`, `Dynacell`, `SRA`). *(signature)* |
| `name` | string | Required | Human-readable dataset name. |
| `modality` | string | Required | High-level data modality. One of `DatasetModality`. |
| `dataset_type` | string | Required | `raw`, `processed`, or `aggregated`. |
| `locations` | list[DataAsset] | Required (min 1) | The Data Assets that make up this dataset. |
| `governance` | json | Required | Governance and access metadata. See [Governance metadata](#governance-metadata). |
| `metadata` | json | Required on create/update | Scientific metadata. See [Metadata](#metadata). |
| `description` | string | Recommended | Human-readable description of the dataset. |
| `publications` | list[string] | Optional | Related publications, as DOIs or free-text citations. |
| `doi` | string | Optional | Digital Object Identifier for the dataset if it exists. |
| `cross_db_references` | string | Optional | External database references (e.g. GEO accessions, SRA run IDs, EMPIAR IDs). |
| `is_latest` | boolean | Optional (default `true`) | `true` if this is the most recent version of the canonical dataset. |
| `record_schema_version` | string | Optional | Version of the catalog record schema (e.g. `v1.5.0`). Defaults to the schema version the client was built against. |
| `metadata_schema` | list[string] | Optional | URI(s) of external metadata schema(s) that apply to this dataset. |
| `data_quality` | json | Optional | Data quality evaluation results. See [Data quality](#data-quality). |
| `record_version` | integer | Response only | Increments on every non-tombstone update. |

<a name="audit-fields"></a>

### Audit fields

Present on every response.

| Field | Type | Description |
|---|---|---|
| `id` | string (UUIDv7) | Primary key. |
| `created_at` | datetime | Creation timestamp (UTC). |
| `last_modified_at` | datetime | Last update timestamp (UTC). |
| `tombstoned` | boolean | Soft-delete flag. |

### Shared types

#### OntologyEntry

A labeled ontology reference, reused across sample and experiment metadata.

| Field | Type | Level | Description |
|---|---|---|---|
| `label` | string | Recommended | Human-readable term (e.g. `Homo sapiens`). |
| `ontology_id` | string | Recommended | Ontology identifier (e.g. `NCBITaxon:9606`). |

#### TissueEntry

Extends `OntologyEntry` with a tissue type.

| Field | Type | Level | Description |
|---|---|---|---|
| `label` | string | Recommended | Human-readable term (e.g. `liver`). |
| `ontology_id` | string | Recommended | Ontology identifier (e.g. `UBERON:0002107`). |
| `type` | string | Optional | Controlled value: `tissue`, `organoid`, `cell culture`, `cell line`, or `organelle`. |

### Metadata

`metadata` is a JSON object with three sub-keys. All metadata models allow extra keys,
so additional domain-specific or team-specific fields are preserved rather than
rejected.

| Field | Type | Level | Description |
|---|---|---|---|
| `experiment` | json | Recommended | Experimental setup and instrument information. See [Experimental metadata](#experimental-metadata). |
| `sample` | json | Recommended | Biological sample information. See [Sample metadata](#sample-metadata). |
| `data_summary` | json | Recommended | Content descriptors and modality-specific measurements. See [Data summary metadata](#data-summary-metadata). |

#### Experimental metadata

| Field | Type | Level | Description |
|---|---|---|---|
| `sub_modality` | string | Recommended | More granular specification of the experimental procedure (e.g. `scRNA-seq`, `confocal`, `brightfield`, `bulk`). |
| `assay` | list[OntologyEntry] | Recommended | Assay(s) used to produce the dataset. Recommended ontology: **EFO** (e.g. `EFO:0022605`), **FBbi** for imaging (e.g. `FBbi:00100015`). |
| `machine_information` | json | Optional | Information about the instrument used for data generation (e.g. `{"microscope": "Zeiss LSM 980"}`). |
| `experimental_protocols` | json | Optional | Protocol details for the experiment. |

#### Sample metadata

| Field | Type | Level | Description |
|---|---|---|---|
| `organism` | list[OntologyEntry] | Recommended | Source organism(s). Recommended ontology: **NCBITaxon** (e.g. `NCBITaxon:9606` for human). |
| `tissue` | list[TissueEntry] | Recommended | Tissue(s) the biosamples were derived from. Recommended ontology: **UBERON** for tissue; see [Recommended ontologies](#recommended-ontologies) for cell-line, cell-culture, and organelle cases. |
| `cell_strain` | list[OntologyEntry] | Optional | Cell line or strain the sample came from (e.g. `{"label": "HeLa", "ontology_id": "CLO:0003684"}`). New in v1.5.0. |
| `development_stage` | list[OntologyEntry] | Optional | Development stage(s) of the organism or patient. Recommended ontology is organism-specific — see [Recommended ontologies](#recommended-ontologies). |
| `disease` | list[OntologyEntry] | Optional | Associated disease(s). Recommended ontology: **MONDO**; use `PATO:0000461` for normal/healthy and `MONDO:0021178` for injury. |
| `perturbation` | list[json] | Optional | Applied perturbation(s). Recommended structure: follow CELLxGENE's [`genetic_perturbations` schema](https://github.com/chanzuckerberg/single-cell-curation/blob/main/schema/7.1.0/schema.md#genetic_perturbations) — see [Recommended ontologies](#recommended-ontologies). |
| `sample_parent` | json | Optional | Sample parentage and replication information. |
| `sample_preparation_protocols` | json | Optional | Sample preparation protocol details. |

#### Recommended ontologies

To keep metadata interoperable, populate the `ontology_id` of each entry using the
ontology recommended below. These follow the
[CZI cross-modality standard](https://github.com/chanzuckerberg/data-guidance/blob/main/standards/cross-modality/1.1.0/schema.md);
the `label` should be the ontology term's preferred label.

| Field | Recommended ontology | Notes & special values |
|---|---|---|
| `organism` | **NCBITaxon** | e.g. `NCBITaxon:9606` (human), `NCBITaxon:10090` (mouse), `NCBITaxon:7955` (zebrafish), `NCBITaxon:7227` (Drosophila), `NCBITaxon:6239` (C. elegans). |
| `assay` | modality-specific | Default: Experimental Factor Ontology, e.g. `EFO:0022605`; for imaging use Biological Imaging Methods Ontology, e.g. `FBbi:00000243`. |
| `disease` | **MONDO** | Use `PATO:0000461` for normal/healthy and `MONDO:0021178` for injury. |
| `development_stage` | organism-specific | **HsapDv** (human), **MmusDv** (mouse), **WBls** (C. elegans), **ZFS** (zebrafish), **FBdv** (Drosophila); `UBERON:0000105` (life cycle stage) for other organisms. Use `unknown` if unavailable and `na` for cell lines. |
| `tissue` | depends on `type` | **UBERON** for tissue/organoid (or organism-specific **WBbt** / **ZFA** / **FBbt**); **CL** for cell culture; **Cellosaurus** (`CVCL_` prefix) for cell lines; `GO:0005575` (cellular_component) descendants for organelles. |
| `cell_strain` | **CLO** / **Cellosaurus** | e.g. `CLO:0003684` (HeLa). Use Cellosaurus (`CVCL_` prefix) where CLO has no term. |

The `tissue` entry's `type` field is a controlled value: one of `tissue`, `organoid`,
`cell culture`, `cell line`, or `organelle`.

For `perturbation`, follow CELLxGENE's
[`genetic_perturbations` schema](https://github.com/chanzuckerberg/single-cell-curation/blob/main/schema/7.1.0/schema.md#genetic_perturbations)
for the entry structure and its controlled vocabularies. Each record carries a `role`
(`control` or experimental), a gene identifier, and a perturbation strategy from a
fixed set (e.g. `CRISPR activation screen`, `CRISPR interference screen`,
`CRISPR knockout mutant`, `CRISPR knockout screen`, `control`).

#### Data summary metadata

This section covers content descriptors and modality-specific measurements. The fields
below are the most common ones; additional key-value pairs may be added to extend it.

| Field | Type | Level | Modality | Applicable formats | Description |
|---|---|---|---|---|---|
| `cell_count` | integer | Optional | any | — | Number of cells in the dataset. |
| `read_count` | integer | Optional | sequencing | — | Number of reads. |
| `read_length` | integer \| json | Optional | sequencing | — | Average read length, or a map of read lengths to counts. |
| `read_confidence` | float | Optional | sequencing | — | Read confidence score. |
| `axes` | list[json] | Optional | imaging | Zarr | Axis definitions. Each entry: `{ name, type, unit }`. |
| `resolution` | json | Recommended | imaging | Zarr | Spatial and/or temporal resolution. See [ResolutionMetadata](#resolutionmetadata). |
| `dimension` | list[int] | Optional | imaging | Zarr | Array dimensions (e.g. `[Z, Y, X]`). |
| `multiscales` | json | Optional | imaging | Zarr | OME-NGFF multiscale pyramid metadata. |
| `plate` | string \| json | Optional | imaging | Zarr | Plate identifier or plate-level metadata. |
| `well` | string \| json | Optional | imaging | Zarr | Well identifier or well-level metadata. |
| `fov` | string \| json | Optional | imaging | Zarr | Field-of-view identifier or metadata. |
| `channels` | list[ChannelMetadata] | Recommended | imaging | Zarr | Channel information, including biological annotation. See [ChannelMetadata](#channelmetadata). |
| `channel_normalization` | json | Optional | imaging | Zarr | Per-channel normalization statistics, per-dataset and per-timepoint. See [ChannelNormalization](#channelnormalization). |

`dca_schema_version` was removed in v1.5.0. Record external metadata specifications on
the dataset's `metadata_schema` list instead.

##### ResolutionMetadata

| Field | Type | Level | Description |
|---|---|---|---|
| `spatial` | json | Optional | Spatial resolution info (e.g. `{"x": 0.65, "unit": "micrometer"}`). |
| `temporal` | json | Optional | Temporal resolution info (e.g. `{"interval": 30, "unit": "second"}`). |

##### ChannelMetadata

| Field | Type | Level | Description |
|---|---|---|---|
| `name` | string | Recommended | Channel name (e.g. `DAPI`, `GFP`). |
| `index` | integer | Recommended | Zero-based channel index in the image array. |
| `channel_type` | enum | Recommended | `fluorescence`, `chromogenic`, `labelfree`, or `predicted`. |
| `description` | string | Optional | Free-text description of the channel. |
| `biological_annotation` | json | Optional | Biological target details for this channel. See [BiologicalAnnotation](#biologicalannotation). |

##### BiologicalAnnotation

| Field | Type | Level | Description |
|---|---|---|---|
| `biological_target` | string | Recommended | Target biological structure or molecule (e.g. `nucleus`). |
| `marker_type` | enum | Optional | `endogenous_tag`, `live_cell_dye`, `fixed_dye`, or `antibody`. |
| `marker` | string | Optional | Specific marker name (e.g. `DAPI`, `H2B`, `phalloidin`). |

`cpg_labeled_structure` and `cpg_labeled_molecule` were removed in v1.5.0. Record the
targeted structure or molecule in `biological_target` instead.

##### ChannelNormalization

| Field | Type | Level | Description |
|---|---|---|---|
| `dataset_statistics` | IntensityStatistics | Optional | Intensity stats computed over the full dataset. |
| `timepoint_statistics` | dict[string, IntensityStatistics] | Optional | Per-timepoint stats keyed by zero-based timepoint index string. Must cover all timepoints if present. |

##### IntensityStatistics

| Field | Type | Level | Description |
|---|---|---|---|
| `p1` | float | Optional | 1st percentile intensity. |
| `p5` | float | Optional | 5th percentile intensity. |
| `p95` | float | Optional | 95th percentile intensity. |
| `p99` | float | Optional | 99th percentile intensity. |
| `p95_p5` | float | Optional | Robust range: p95 minus p5. |
| `p99_p1` | float | Optional | Wide robust range: p99 minus p1. |
| `mean` | float | Optional | Arithmetic mean of pixel intensities. |
| `std` | float | Optional | Standard deviation of pixel intensities. |
| `median` | float | Optional | Median (50th percentile) intensity. |
| `iqr` | float | Optional | Interquartile range: p75 minus p25. |

### Governance metadata

The `governance` field covers access control and ownership. Additional key-value pairs
are permitted.

| Field | Type | Level | Description |
|---|---|---|---|
| `data_owner` | string | **Required** | Person or team responsible for the data (e.g. `lab-imaging@czi.org`). |
| `access_scope` | string | Recommended (default `internal`) | Whether the data is publicly accessible. Valid values: `public`, `internal`. Lowercased on ingest; unrecognized values fall back to `internal`. |
| `license` | string | Recommended | License governing data use (e.g. `CC-BY-4.0`). |
| `is_pii` | boolean | Recommended | Whether the dataset contains personally identifiable information. |
| `is_phi` | boolean | Recommended | Whether the dataset contains protected health information. |
| `data_steward` | string | Optional | Person or team responsible for day-to-day stewardship. |
| `is_external_reference` | boolean | Optional (default `false`) | `true` if this dataset represents existing external data in the public domain maintained outside Biohub. |
| `embargoed_until` | date | Optional | Date after which the dataset becomes accessible (ISO 8601, e.g. `2027-01-01`). |
| `data_sensitivity` | string | **Deprecated in v1.5.0** | Free-form sensitivity label (`Low`, `Medium`, `High`). Express public visibility via `access_scope` instead; leave unset on new records. |

### Data quality

| Field | Type | Level | Description |
|---|---|---|---|
| `checks_passed` | any | Optional | Quality checks that passed (e.g. `["schema", "checksum"]`). |
| `checks_failed` | any | Optional | Quality checks that failed. |
| `checks_skipped` | any | Optional | Quality checks that were skipped. |
| `metrics` | any | Optional | Quantitative quality metrics (e.g. `{"completeness": 0.97}`). New in v1.5.0. |

### Examples

- Demultiplexed FASTQ files from a sequencer run.
- A single H5AD file in CELLxGENE.
- The frames, tilt-series, and tomograms from a single CryoET acquisition.
- A multi-channel Zarr from a fluorescence imaging field of view.

---

## Lineage Edge

A Lineage Edge records a directed relationship between two datasets, tracking how data
moved from a source to a destination. Lineage can be recorded at the dataset level or
pinned to specific Data Assets within those datasets.

### Constraints

- Relationships are directional: from source to destination.
- `source_data_asset_id` and `destination_data_asset_id` are optional. If omitted, the
  relationship applies to the datasets as a whole rather than to specific files.
- A dataset can have multiple upstream sources and multiple downstream descendants.
- Both source and destination datasets must exist and must not be tombstoned when the
  edge is created.
- If asset-level IDs are provided, each asset must belong to its respective dataset.
- On a dataset version bump, the catalog records a `version_of` edge from the old record
  to the new one and carries the old record's active edges forward, remapping them to
  the new record's assets by URI.

### Lineage types

| Type | Meaning | Example |
|---|---|---|
| `version_of` | Destination is a newer version of the source. | Dataset v1 → Dataset v2 |
| `transformed_from` | Destination was produced by processing the source. | FASTQ → H5AD |
| `copy_of` | Destination is a copy of the source in a different location. | Bruno original → S3 copy |

### Properties

| Field | Type | Level | Description |
|---|---|---|---|
| `source_dataset_id` | string (UUID) | Required | The upstream dataset. |
| `destination_dataset_id` | string (UUID) | Required | The downstream dataset. |
| `lineage_type` | string | Required | `version_of`, `transformed_from`, or `copy_of`. |
| `source_data_asset_id` | string (UUID) | Optional | Specific upstream Data Asset within the source dataset. |
| `destination_data_asset_id` | string (UUID) | Optional | Specific downstream Data Asset within the destination dataset. |
| `metadata` | json | Optional | Additional context, e.g. processing algorithm name, pipeline version, transformation parameters. |

---

## Collection

A Collection is an organizational grouping of datasets. It has no governance rules or
access controls of its own — those always come from the datasets inside it.

Collections can be used to organize data so it maps to how data is actually organized
in the real world. The recommended hierarchy for that is:

```
Study
└── Experiment
    └── Run   ← datasets attach here
```

The hierarchy is expressed by nesting collections inside one another (a collection can
contain sub-collections as well as datasets). The names `Study`, `Experiment`, and `Run`
above are organizational labels carried in each collection's `name`, not `collection_type`
values. A dataset can belong to multiple collections.

### Constraints

- Collections are mutable. Datasets can be added or removed at any time.
- A collection can be empty (e.g. if it is created before the data is registered).
- A collection cannot be more than 4 levels deep.
- Cycles are not permitted in collections and will be rejected at write time.

### Properties

All collection levels share the same schema. Nesting expresses the hierarchy; the
`collection_type` field records what kind of grouping the collection is.

| Field | Type | Level | Description |
|---|---|---|---|
| `canonical_id` | string | Required | Unique identifier for the collection. Stable across versions. |
| `version` | string | Required | Version of the collection. |
| `name` | string | Required | Human-readable name. |
| `collection_owner` | string | Required | Person or team that owns the collection. |
| `collection_type` | string | Optional | Accepted values: `publication`, `training`. |
| `description` | string | Recommended | Human-readable description. |
| `metadata` | json | Optional | Additional metadata. |
| `doi` | string | Optional | DOI for a related publication. |
| `license` | string | Optional | License information. |
| `external_reference` | string | Optional | Reference to the equivalent entity in an external system (e.g. GEO series accession, CryoET Portal deposition ID). |

### Examples

- A `publication` collection for a CellXGene study.
- A `publication` collection for CryoET containing all the data in a CryoET Data
  Portal dataset.
- A `training` collection grouping the datasets used to train a model, including the
  related processed outcomes.

---

## How the entities relate

```
Collection (Study → Experiment → Run)
└── contains (many-to-many) ──► Dataset
                                 ├── has (one-to-many) ──► Data Asset
                                 │                          (files/folders on storage)
                                 │
                                 └── connected by ──► Lineage Edge ──► Dataset
                                                       (version_of /
                                                        transformed_from /
                                                        copy_of)
```

A dataset always has at least one data asset and exactly one governance block.
Collections and lineage edges are optional — a dataset can exist without belonging to
any collection and without any lineage edges.

---

## API models

The Dataset schema maps to Pydantic models in the API's `app/models/dataset.py`:

| Model | Role |
|---|---|
| `DatasetBase` | Shared fields (excludes `metadata` — see note below). |
| `DatasetRequest` | Create/update; declares `metadata: DatasetMetadata`, requires ≥1 `locations`. |
| `DatasetResponse` | `from_attributes=True`; adds the [audit fields](#audit-fields) and `record_version`. |
| `DatasetWithRelationsResponse` | Extends the response with `incoming_lineage`, `outgoing_lineage`, and `collections`. |

**`metadata` naming.** SQLAlchemy reserves `Base.metadata`, so the response model
exposes the column under the ORM attribute `dataset_metadata` with
`serialization_alias="metadata"` — the JSON wire format is `metadata` in both
directions.
