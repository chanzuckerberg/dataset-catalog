# Scientific Dataset Catalog — Schema & Definitions

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

---

## Definitions

| Term | Meaning |
|---|---|
| **Required** | The field MUST be present on every write. |
| **Optional** | The field MAY be omitted. |
| **Signature field** | A field that participates in the record's identity. Changing it does not patch in place — see *Tombstone*. |
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

### Properties

| Field | Type | Required | Description |
|---|---|----------|---|
| `storage_platform` | string | Yes      | Storage backend. Valid values: `s3`, `sf_hpc`, `chi_hpc`, `ny_hpc`, `reef`, `kelp`, `atoll`, `external`, `other`. Callers name it; nothing derives it from the URI. |
| `location_uri` | string | Yes      | Full URI with storage scheme (e.g. `s3://`, `gs://`, `https://`, `globus://`, `file://`). |
| `asset_type` | string | Yes      | `file` or `folder`. |
| `size_bytes` | integer | No       | Total size in bytes. For folder assets, the sum of all included files. |
| `checksum` | string | No       | Integrity hash. Single files use a standard hash; folders use a Merkle-style hash over sorted individual file checksums. |
| `checksum_alg` | string | No       | Algorithm used to compute the checksum (e.g. `md5`, `sha256`, `blake3`). |
| `encoding` | string | No       | Content encoding (e.g. `gzip`, `zstd`). |
| `file_format` | string | No       | File format or MIME type (e.g. `parquet`, `fasta`, `json`). |
| `description` | string | No       | Human-readable description of this specific asset. |
| `file_count` | integer | No       | Number of files in the folder. For folder-type assets only. |

### Examples

- A single H5AD file.
- A Zarr folder containing one field of view.
- A reference genome FASTA hosted externally.

---

## Dataset

A Dataset is a named, versioned container for one or more Data Assets. Datasets are
registered at meaningful points in a scientific workflow: when data comes off an
instrument, or when processing produces a new output worth tracking. Scientific
context (what was the biological context?), governance information (who can access this?),
and modality-specific metadata all live at the dataset level.

### Dataset types

**Raw** are data produced by a single experimental acquisition from a machine — one pass through
an instrument or pipeline under consistent conditions (same organism, same assay, same
modality). If two groups of files came from the same run under the same conditions,
they go in one dataset. If anything changes between them, register them separately.

**Processed** are always new datasets. When an existing dataset is processed,
the output goes in a new dataset record linked back to its source via a lineage edge.
The original is never modified. Any qualitative change to the raw dataset such as preprocessing,
makes it a processed dataset. A processed dataset can be derived from multiple source datasets
across different samples, assays, or modalities.

The `dataset_type` field records this distinction as `raw` or `processed`.

### Signature fields

The combination of `canonical_id`, `version`, and `project` uniquely identifies a
dataset. Changing any of these fields, tombstones the existing record, sets `is_latest=false` on it,
and creates a new record.

| Field | Description                                                                                 |
|---|---------------------------------------------------------------------------------------------|
| `canonical_id` | Human readable stable identifier, unique within a project. Does not change across versions. |
| `version` | Version string for the dataset.                                                             |
| `project` | The project this dataset belongs to.                                                        |

### Update behavior

- Changes to any non-signature field (`name`, `description`, `modality`, `metadata`,
  `governance`, etc.) are applied in place and increment `record_version`.
- Changes to `locations` are handled differentially: new assets are added, assets
  missing from the update are tombstoned, and existing assets follow the
  [Data Asset signature rules](#signature-fields) above.
- Tombstoned datasets cannot be updated.

### Properties — core fields

| Field | Type | Required | Description |
|---|---|---|---|
| `canonical_id` | string | Yes | Stable external identifier, unique within a project. Does not change across versions. |
| `version` | string | No | Version of the dataset. Defaults to `1.0.0`. Still a signature field — see [Signature fields](#signature-fields-1). |
| `project` | string | Yes | The project this dataset belongs to (e.g. `CellXGene`, `CryoET`, `BCP`, `Dynacell`, `SRA`). |
| `name` | string | Yes | Human-readable dataset name. Safe to fix later — it edits in place. |
| `description` | string | No | Human-readable description of the dataset. |
| `modality` | string | Yes | High-level data modality. Valid values: `imaging`, `sequencing`, `mass spec`, `text`, `unknown`. |
| `dataset_type` | string | No | `raw` or `processed`. |
| `is_latest` | boolean | No | `true` if this is the most recent version of the canonical dataset. Defaults to `true`. |
| `doi` | string | No | Digital Object Identifier for the dataset if it exists. |
| `cross_db_references` | string | No | Comma-separated external database references (e.g. GEO accessions, SRA run IDs, EMPIAR IDs). |
| `locations` | list[DataAsset] | Yes | The Data Assets that make up this dataset. At least one is required. |
| `record_schema_version` | string | No | Version of the catalog record schema. Defaults to `v1.5.0`. |
| `metadata_schema` | list[string] | No | List of metadata schemas that apply to this dataset. |
| `metadata` | json | Yes | Scientific metadata. See [Metadata](#metadata) below. |
| `governance` | json | Yes | Governance and access metadata. See [Governance metadata](#governance-metadata) below. |
| `data_quality` | json | No | Data quality evaluation results. See [Data quality](#data-quality) below. |

### Metadata

`metadata` is a JSON object with three sub-keys. Additional key-value pairs at the top
level are permitted for domain-specific or team-specific needs.

| Field | Type | Required | Description |
|---|---|---|---|
| `experiment` | json | No | Experimental setup and instrument information. See [Experimental metadata](#experimental-metadata). |
| `sample` | json | No | Biological sample information. See [Sample metadata](#sample-metadata). |
| `data_summary` | json | No | Content descriptors and modality-specific measurements. See [Data summary metadata](#data-summary-metadata). |

#### Experimental metadata

| Field | Type | Required | Description                                                                                                                                                     |
|---|---|---|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `sub_modality` | string | No | More granular specification of the experimental procedure (e.g. `scRNA-seq`, `brightfield`, `bulk`).                                                            |
| `assay` | list[json] | No | Assay(s) used to produce the dataset. Each entry: `{ label, ontology_id }`. Recommended ontology: **EFO** (e.g. `EFO:0022605`), **FBbi** (eg. `FBbi:00100015`). |
| `machine_information` | json | No | Information about the instrument used for data generation.                                                                                                      |
| `experimental_protocols` | json | No | Protocol details for the experiment.                                                                                                                            |

#### Sample metadata

| Field | Type | Required | Description |
|---|---|---|---|
| `organism` | list[json] | No | Source organism(s). Each entry: `{ label, ontology_id }`. Recommended ontology: **NCBITaxon** (e.g. `NCBITaxon:9606` for human). |
| `tissue` | list[json] | No | Tissue(s) the biosamples were derived from. Each entry: `{ label, ontology_id, type }`. Recommended ontology: **UBERON** for tissue; see [Recommended ontologies](#recommended-ontologies) for cell-line, cell-culture, and organelle cases. |
| `development_stage` | list[json] | No | Development stage(s) of the organism or patient. Each entry: `{ label, ontology_id }`. Recommended ontology is organism-specific — see [Recommended ontologies](#recommended-ontologies). |
| `disease` | list[json] | No | Associated disease(s). Each entry: `{ label, ontology_id }`. Recommended ontology: **MONDO**; healthy or normal material is exactly `PATO:0000461`. |
| `perturbation` | list[json] | No | Codebook of the distinct perturbations applied — one entry per perturbation. See [Perturbation](#perturbation). Stored unvalidated. |
| `sample_parent` | json | No | Sample parentage and replication information. |
| `sample_preparation_protocols` | json | No | Sample preparation protocol details. |

#### Recommended ontologies

To keep metadata interoperable, populate the `ontology_id` of each entry using the
ontology recommended below. These follow the
[CZI cross-modality standard](https://github.com/chanzuckerberg/data-guidance/blob/main/standards/cross-modality/1.1.0/schema.md);
the `label` should be the ontology term's preferred label.

| Field | Recommended ontology | Notes & special values                                                                                                                                                                                                       |
|---|--------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `organism` | **NCBITaxon**      | e.g. `NCBITaxon:9606` (human), `NCBITaxon:10090` (mouse), `NCBITaxon:7955` (zebrafish), `NCBITaxon:7227` (Drosophila), `NCBITaxon:6239` (C. elegans).                                                                        |
| `assay` | modality-specific  | Default: Experimental Factor Ontology, e.g. `EFO:0022605`, for imaging use Biological Imaging Methods Ontology eg: `FBbi:00000243`                                                                                                          |
| `disease` | **MONDO**          | Healthy or normal material is exactly `PATO:0000461` — not a MONDO term, and not omitted. Anything else takes the most specific MONDO term you can justify.                                                                    |
| `development_stage` | organism-specific  | **HsapDv** (human), **MmusDv** (mouse), **WBls** (C. elegans), **ZFS** (zebrafish), **FBdv** (Drosophila); **UBERON** for anything else. Cell lines take the `not_applicable` sentinel as the `label`, with no `ontology_id`. |
| `tissue` | depends on `type`  | **UBERON** for tissue/organoid (or organism-specific **WBbt** / **ZFA** / **FBbt**); **CL** for cell culture; **Cellosaurus** (`CVCL_` prefix) for cell lines; `GO:0005575` (cellular_component) descendants for organelles. |

The `tissue` entry's `type` field is a controlled value: one of `tissue`, `organoid`,
`cell culture`, `cell line`, or `organelle`.

#### Perturbation

`perturbation` is a **codebook**: it lists each distinct perturbation applied to the
dataset once, rather than recording an assignment per cell or per well. Per-cell and
per-well assignment stays in the data itself, keyed back to these entries by `id`.

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | No | Identifier for this perturbation, referenced from the data. |
| `type` | string | No | `chemical`, `protein`, `genetic`, `environmental`, `combination`, `none`, `other`, or `unknown`. |
| `role` | string | No | `treatment`, `negative_control`, `positive_control`, or `untreated`. |

Entries are stored unvalidated — the catalog does not reject unknown `type` or `role`
values, so a typo will be persisted as written. Additional keys may be added per entry.

#### Data summary metadata

This section covers content descriptors and modality-specific measurements. The fields
below are the most common ones; additional key-value pairs may be added to extend it.

| Field | Type | Required | Modality | Applicable formats | Description |
|---|---|---|---|---|---|
| `cell_count` | integer | No | any | — | Number of cells in the dataset. |
| `read_count` | integer | No | sequencing | — | Number of reads. |
| `read_length` | integer \| json | No | sequencing | — | Average read length, or a map of read lengths to counts. |
| `read_confidence` | float | No | sequencing | — | Read confidence score. |
| `axes` | list[json] | No | imaging | Zarr | Axis definitions. Each entry: `{ name, type, unit }`. |
| `resolution` | json | No | imaging | Zarr | Spatial and/or temporal resolution. See [ResolutionMetadata](#resolutionmetadata). |
| `dimension` | list[int] | No | imaging | Zarr | Pixel dimensions (e.g. `[2048, 2048]`). |
| `multiscales` | json | No | imaging | Zarr | Multiscale pyramid metadata. |
| `plate` | string \| json | No | imaging | Zarr | Plate-level information. |
| `well` | string \| json | No | imaging | Zarr | Well-level information. |
| `fov` | string \| json | No | imaging | Zarr | Field of view used. |
| `channels` | list[ChannelMetadata] | No | imaging | Zarr | Channel information, including biological annotation and normalization statistics. See [ChannelMetadata](#channelmetadata). |
| `channel_normalization` | json | No | imaging | Zarr | Per-channel normalization statistics, per-dataset and per-timepoint. See [ChannelNormalization](#channelnormalization). |

##### ResolutionMetadata

| Field | Type | Required | Description |
|---|---|---|---|
| `spatial` | json | No | Spatial resolution info (e.g. units, pixel size). |
| `temporal` | json | No | Temporal resolution info (e.g. frame interval). |

##### ChannelMetadata

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | No | Channel name as written in the image store — match it exactly so the channel can be located in the array. |
| `index` | integer | No | Zero-based position of this channel on the channel axis. |
| `description` | string | No | Free text for what the structured channel fields can't carry — filter sets, exposure, acquisition notes. |
| `channel_type` | string | No | How the signal was produced. Recommended values (DCA v0.2): `fluorescence`, `chromogenic`, `labelfree`, `predicted`. Not enforced. |
| `biological_annotation` | json | No | Biological target details for this channel. See [BiologicalAnnotation](#biologicalannotation). |

##### BiologicalAnnotation

| Field | Type | Required | Description |
|---|---|---|---|
| `biological_target` | string | No | The structure or molecule the channel reports on (e.g. `nucleus`, `F-actin`). |
| `marker_type` | string | No | How the target was labelled. Recommended values (DCA v0.2): `endogenous_tag`, `live_cell_dye`, `fixed_dye`, `antibody`. Not enforced. |
| `marker` | string | No | The labelling reagent itself (e.g. `DAPI`, `anti-tubulin`). |

##### ChannelNormalization

| Field | Type | Required | Description |
|---|---|---|---|
| `dataset_statistics` | IntensityStatistics | No | Intensity stats computed over the full dataset. |
| `timepoint_statistics` | dict[string, IntensityStatistics] | No | Per-timepoint stats keyed by zero-based timepoint index string. Must cover all timepoints if present. |

##### IntensityStatistics

| Field | Type | Required | Description |
|---|---|---|---|
| `p1` | float | No | 1st percentile intensity. |
| `p5` | float | No | 5th percentile intensity. |
| `p95` | float | No | 95th percentile intensity. |
| `p99` | float | No | 99th percentile intensity. |
| `p95_p5` | float | No | Robust range: p95 minus p5. |
| `p99_p1` | float | No | Wide robust range: p99 minus p1. |
| `mean` | float | No | Arithmetic mean of pixel intensities. |
| `std` | float | No | Standard deviation of pixel intensities. |
| `median` | float | No | Median (50th percentile) intensity. |
| `iqr` | float | No | Interquartile range: p75 minus p25. |

### Governance metadata

The `governance` field covers access control and ownership. Additional key-value pairs
are permitted.

| Field | Type | Required | Description                                                                                                                    |
|---|---|---|--------------------------------------------------------------------------------------------------------------------------------|
| `data_steward` | string | **Yes** | Person or org that defines the standards and best practices for the data's accuracy, quality and completeness, and ingests and formats datasets to meet them. |
| `access_scope` | string | No | Gates the visibility of the record. Exactly `internal` (the default) or `public`. Any other string is accepted and lowercased rather than rejected — a typo like `internel` hides the record from the filter everyone searches with. |
| `license` | string | No | License name (e.g. `MIT`, `CC-BY-4.0`) or a link to the terms of use.                                                          |
| `data_sensitivity` | string | No | `Low`, `Medium`, or `High`. Separate from `access_scope` — filter on `access_scope`, not on this.                               |
| `is_pii` | boolean | No | Personally identifiable information: names, contact details, dates of birth, precise locations, government or institutional IDs, or any combination that could re-identify a person. "I am not sure" is not `false`. |
| `is_phi` | boolean | No | Protected health information: clinical, diagnostic, treatment, or payment data tied to an identifiable individual. Narrower than PII but with stricter handling obligations, which is why it is a separate flag. Data can be one, both, or neither. |
| `data_owner` | string | No | Person or org that approves the data's governance policies, classification, usage guidelines and publication. Accountable for compliance, including dataset tracking and legal review. |
| `is_external_reference` | boolean | No | Marks the record as a pointer to externally-owned data rather than data in Biohub storage. Defaults to `false`. |
| `embargoed_until` | date | No | ISO date until which access is restricted. Accepts `YYYY-MM-DD` only — other date forms are rejected rather than coerced. |

### Data quality

| Field | Type | Required | Description |
|---|---|---|---|
| `checks_passed` | any | No | Data-quality checks that ran and passed. |
| `checks_failed` | any | No | Data-quality checks that ran and failed. Record them rather than omitting them — a consumer would otherwise read the silence as a clean bill of health. |
| `checks_skipped` | any | No | Checks that did not run, and why, if the reason is worth carrying. |
| `report_assets` | list[json] | No | Human-readable QC reports, one entry per file: `{ name, uri }`, e.g. `{"name": "fastqc", "uri": "s3://bucket/qc/fastqc.html"}`. Pointers only — the catalog never fetches or hosts them. |
| `metrics_assets` | list[json] | No | Machine-readable metric files backing the checks, one entry per file: `{ name, uri }`, e.g. `{"name": "multiqc", "uri": "s3://bucket/qc/multiqc_data.json"}`. |
| `metrics` | list[json] | No | The metric values themselves, inline — one entry per metric carrying at least its name and value, e.g. `{"name": "duplication_rate", "value": 0.12}`. Use it for the handful worth reading without opening a file; the bulk belongs in `metrics_assets`. |

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

### Lineage types

| Type | Meaning | Example |
|---|---|---|
| `version_of` | Destination is a newer version of the source. | Dataset v1 → Dataset v2 |
| `transformed_from` | Destination was produced by processing the source. | FASTQ → H5AD |
| `copy_of` | Destination is a copy of the source in a different location. | Bruno original → S3 copy |

### Properties

| Field | Type | Required | Description |
|---|---|---|---|
| `source_dataset_id` | string (UUID) | Yes | The upstream dataset. |
| `destination_dataset_id` | string (UUID) | Yes | The downstream dataset. |
| `lineage_type` | string | Yes | `version_of`, `transformed_from`, or `copy_of`. |
| `source_data_asset_id` | string (UUID) | No | Specific upstream Data Asset within the source dataset. |
| `destination_data_asset_id` | string (UUID) | No | Specific downstream Data Asset within the destination dataset. |
| `metadata` | json | No | Additional context, e.g. processing algorithm name, pipeline version, transformation parameters. |

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
- Cycles are not permitted and are rejected at write time with a `400`.
- Nesting deeper than 4 levels is discouraged as a modelling convention, but is not
  rejected by the API.

### Properties

All collection levels share the same schema. Nesting expresses the hierarchy; the
`collection_type` field records what kind of grouping the collection is.

| Field | Type | Required | Description                                                                                                        |
|---|---|---|--------------------------------------------------------------------------------------------------------------------|
| `canonical_id` | string | Yes | Unique identifier for the collection. Stable across versions.                                                      |
| `version` | string | Yes | Version of the collection.                                                                                         |
| `name` | string | Yes | Human-readable name.                                                                                               |
| `collection_owner` | string | Yes | Person or team that owns the collection.                                                                           |
| `collection_type` | string | No | Accepted values: `publication`, `training`.                                                               |
| `description` | string | No | Human-readable description.                                                                                        |
| `metadata` | json | No | Additional metadata about the collection itself.                                                                   |
| `doi` | string | No | DOI for a related publication.                                                                                     |
| `license` | string | No | License information.                                                                                               |
| `external_reference` | string | No | Reference to the equivalent entity in an external system (e.g. GEO series accession, CryoET Portal deposition ID). |

### Membership entries

A collection's members are datasets, child collections, or both. Each membership is its
own record, distinct from the member itself, and carries optional metadata describing
the *relationship* rather than the member — a run's position in a series, say, or why a
dataset was included in a training set.

| Field | Type | Required | Description |
|---|---|---|---|
| `entry_type` | string | Yes | `dataset` or `collection`. Set by the API on read; determined by the endpoint used on write. |
| `metadata` | json | No | Metadata about this membership. Removed with the membership, not with the member. |

Listing a collection's contents returns both entry types in one paginated list,
discriminated by `entry_type`.

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
