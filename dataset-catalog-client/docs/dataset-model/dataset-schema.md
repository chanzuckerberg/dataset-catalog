# DatasetRequest Schema Reference

`DatasetRequest` is the payload used to create or update a dataset. This document is the authoritative field-level reference.

**Required** fields must always be present. **Signature** fields form the dataset's identity — changing any signature field tombstones the existing record and creates a new one with a new UUID.

## Contents

- [Top-level fields](#top-level-fields)
- [DataAsset](#dataasset)
- [GovernanceMetadata](#governancemetadata)
- [DataQualityChecks](#dataqualitychecks)
- [DatasetMetadata](#datasetmetadata)
- [ExperimentMetadata](#experimentmetadata)
- [SampleMetadata](#samplemetadata)
- [DataSummaryMetadata](#datasummarymetadata)
- [ChannelMetadata](#channelmetadata)
- [ChannelNormalization](#channelnormalization)
- [Full schema tree](#full-schema-tree)

---

## Top-level fields

| Field | Required | Type | Signature | Description |
|---|---|---|---|---|
| `canonical_id` | Required | string | Yes | Stable external identifier for the dataset (e.g. `rna-seq-batch-42`). |
| `version` | Optional | string | Yes | Dataset version. Defaults to `"1.0.0"`. |
| `project` | Optional | string | Yes | Project the dataset belongs to. |
| `name` | Required | string | | Human-readable display name. |
| `description` | Optional | string | | Free-text description of the dataset. |
| `modality` | Required | enum | | Data modality: `imaging`, `sequencing`, `mass_spec`, `unknown`. |
| `doi` | Optional | string | | Digital Object Identifier for the dataset. |
| `cross_db_references` | Optional | string | | References to other databases or external IDs. |
| `dataset_type` | Optional | enum | | Dataset type: `raw` or `processed`. |
| `is_latest` | Optional | boolean | | Whether this is the latest version. Defaults to `true`. |
| `record_schema_version` | Optional | string | | Schema version tag. Defaults to `"v1.3.0"`. |
| `metadata_schema` | Optional | string | | URI or name of the metadata schema applied. |
| `locations` | Required | list[DataAsset] | | At least one data asset location (min length 1). |
| `governance` | Required | GovernanceMetadata | | Access control and ownership block. |
| `data_quality` | Optional | DataQualityChecks | | Quality check results. |
| `metadata` | Required | DatasetMetadata | | Experiment, sample, and data summary metadata envelope. |

---

## DataAsset

Each entry in `locations`. At least one entry is required.

| Field | Required | Type | Signature | Description                                           |
|---|---|---|---|-------------------------------------------------------|
| `location_uri` | Required | string | Yes | URI of the file or folder (e.g. `s3://bucket/path/`). |
| `asset_type` | Required | enum | Yes | `file` or `folder`.                                   |
| `size_bytes` | Optional | integer | Yes | File or folder size in bytes.                         |
| `checksum` | Optional | string | Yes | Checksum hash value.                                  |
| `checksum_alg` | Optional | string | Yes | Checksum algorithm (e.g. `md5`, `sha256`, `blake3`).  |
| `encoding` | Optional | string | | File encoding (e.g. `zarr`, `h5ad`).                  |
| `file_format` | Optional | string | | File format (e.g. `parquet`, `tiff`, `fastq`).        |
| `description` | Optional | string | | Description of this asset.                            |
| `storage_platform` | Optional | enum | | Auto-inferred from URI for some cases if absent       |
| `file_count` | Optional | integer | | Number of files (folder assets only).                 |

---

## GovernanceMetadata

| Field | Required | Type | Description |
|---|---|---|---|
| `license` | Optional | string | License identifier (e.g. `CC-BY-4.0`). |
| `data_sensitivity` | Optional | string | Sensitivity classification of the data. |
| `access_scope` | Optional | string | Visibility scope: `public` or `internal`. Defaults to `internal`. Normalized to lowercase. |
| `is_pii` | Optional | boolean | Whether the dataset contains Personally Identifiable Information. |
| `is_phi` | Optional | boolean | Whether the dataset contains Protected Health Information. |
| `data_steward` | Optional | string | Email or name of the data steward responsible for the dataset. |
| `data_owner` | Optional | string | Email or name of the data owner. |
| `is_external_reference` | Optional | boolean | Whether this is a reference to an external dataset. Defaults to `false`. |
| `embargoed_until` | Optional | date | Date until which the dataset is embargoed (ISO 8601, e.g. `2025-12-31`). |

---

## DataQualityChecks

| Field | Required | Type | Description |
|---|---|---|---|
| `checks_passed` | Optional | any | Results or count of quality checks that passed. |
| `checks_failed` | Optional | any | Results or count of quality checks that failed. |
| `checks_skipped` | Optional | any | Results or count of quality checks that were skipped. |

---

## DatasetMetadata

Top-level metadata envelope. All three sub-blocks are optional.

| Field | Required | Type | Description |
|---|---|---|---|
| `experiment` | Optional | ExperimentMetadata | Experimental setup details. |
| `sample` | Optional | SampleMetadata | Biological sample details. |
| `data_summary` | Optional | DataSummaryMetadata | Content descriptors and modality-specific measurements. |

---

## ExperimentMetadata

| Field | Required | Type | Description |
|---|---|---|---|
| `sub_modality` | Optional | string | Sub-modality of the experiment (e.g. `scRNA-seq`, `brightfield`, `bulk`). |
| `machine_information` | Optional | dict | Instrument/machine metadata (free-form key-value). |
| `experimental_protocols` | Optional | dict | Protocol details (free-form key-value). |
| `assay` | Optional | list[OntologyEntry] | Assay type(s) with ontology labels and IDs. |

### OntologyEntry — assay

| Field | Required | Type | Description |
|---|---|---|---|
| `label` | Optional | string | Human-readable ontology term label (e.g. `10x 3' v3`). |
| `ontology_id` | Optional | string | Ontology term ID (e.g. `EFO:0009922`). |

---

## SampleMetadata

| Field | Required | Type | Description |
|---|---|---|---|
| `perturbation` | Optional | list[dict] | Perturbation details (free-form list of dicts). |
| `sample_parent` | Optional | dict | Parent sample reference (free-form). |
| `sample_preparation_protocols` | Optional | dict | Sample preparation protocol details (free-form). |
| `organism` | Optional | list[OntologyEntry] | Organism(s) the sample came from. |
| `tissue` | Optional | list[TissueEntry] | Tissue source(s). |
| `development_stage` | Optional | list[OntologyEntry] | Developmental stage(s) of the sample. |
| `disease` | Optional | list[OntologyEntry] | Disease state(s) of the sample. |

### OntologyEntry — organism / development_stage / disease

| Field | Required | Type | Description |
|---|---|---|---|
| `label` | Optional | string | Human-readable ontology term label (e.g. `Homo sapiens`). |
| `ontology_id` | Optional | string | Ontology term ID (e.g. `NCBITaxon:9606`, `MONDO:0004975`). |

### TissueEntry

| Field | Required | Type | Description |
|---|---|---|---|
| `label` | Optional | string | Human-readable tissue ontology label (e.g. `liver`). |
| `ontology_id` | Optional | string | Ontology term ID (e.g. `UBERON:0002107`). |
| `type` | Optional | string | Tissue type qualifier (e.g. `primary`, `cell line`). |

---

## DataSummaryMetadata

| Field | Required | Type | Description |
|---|---|---|---|
| `cell_count` | Optional | integer | Total number of cells in the dataset. |
| `read_count` | Optional | integer | Total number of sequencing reads. |
| `read_length` | Optional | integer \| dict | Read length as a fixed integer, or a dict mapping lengths to counts. |
| `read_confidence` | Optional | float | Mean read quality/confidence score. |
| `dimension` | Optional | list[integer] | Image dimensions (e.g. `[Z, Y, X]`). |
| `well` | Optional | string \| list[string] | Well ID(s) for plate-based experiments. |
| `fov` | Optional | string \| list[string] | Field-of-view ID(s). |
| `resolution` | Optional | ResolutionMetadata | Spatial/temporal resolution (imaging). |
| `dca_schema_version` | Optional | string | DCA metadata schema version string. |
| `channels` | Optional | list[ChannelMetadata] | Per-channel metadata. |
| `channel_normalization` | Optional | ChannelNormalization | Normalization statistics across channels. |

### ResolutionMetadata

| Field | Required | Type | Description |
|---|---|---|---|
| `spatial` | Optional | dict | Spatial resolution info (free-form, e.g. units, pixel size). |
| `temporal` | Optional | dict | Temporal resolution info (free-form, e.g. frame interval). |

---

## ChannelMetadata

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | Optional | string | Channel name (e.g. `DAPI`, `GFP`). |
| `index` | Optional | integer | Zero-based channel index in the image array. |
| `description` | Optional | string | Free-text description of the channel. |
| `channel_type` | Optional | enum | `fluorescence`, `chromogenic`, `labelfree`, or `predicted`. |
| `biological_annotation` | Optional | BiologicalAnnotation | Biological target details for this channel. |

### BiologicalAnnotation

| Field | Required | Type | Description |
|---|---|---|---|
| `biological_target` | Optional | string | Target biological structure or molecule (e.g. `nucleus`). |
| `marker_type` | Optional | enum | `endogenous_tag`, `live_cell_dye`, `fixed_dye`, or `antibody`. |
| `marker` | Optional | string | Specific marker name (e.g. `H2B`, `phalloidin`). |
| `cpg_labeled_structure` | Optional | string | CZI CPG labeled structure. |
| `cpg_labeled_molecule` | Optional | string | CZI CPG labeled molecule. |

---

## ChannelNormalization

| Field | Required | Type | Description |
|---|---|---|---|
| `dataset_statistics` | Optional | IntensityStatistics | Intensity stats computed over the full dataset. |
| `timepoint_statistics` | Optional | dict[string, IntensityStatistics] | Per-timepoint stats keyed by zero-based timepoint index string. Must cover all timepoints if present. |

### IntensityStatistics

| Field | Required | Type | Description |
|---|---|---|---|
| `p1` | Optional | float | 1st percentile intensity. |
| `p5` | Optional | float | 5th percentile intensity. |
| `p95` | Optional | float | 95th percentile intensity. |
| `p99` | Optional | float | 99th percentile intensity. |
| `p95_p5` | Optional | float | Robust range: p95 minus p5. |
| `p99_p1` | Optional | float | Wide robust range: p99 minus p1. |
| `mean` | Optional | float | Arithmetic mean of pixel intensities. |
| `std` | Optional | float | Standard deviation of pixel intensities. |
| `median` | Optional | float | Median (50th percentile) intensity. |
| `iqr` | Optional | float | Interquartile range: p75 minus p25. |

---

## Full schema tree

```
DatasetRequest
├── canonical_id*          (required, signature)
├── version                (signature)
├── project                (signature)
├── name*                  (required)
├── modality*              (required)
├── description
├── doi
├── cross_db_references
├── dataset_type
├── is_latest
├── record_schema_version
├── metadata_schema
│
├── locations[]*           (required, min 1)
│   └── DataAsset
│       ├── location_uri*  (required, signature)
│       ├── asset_type*    (required, signature)
│       ├── size_bytes     (signature)
│       ├── checksum       (signature)
│       ├── checksum_alg   (signature)
│       ├── encoding
│       ├── file_format
│       ├── description
│       ├── storage_platform
│       └── file_count
│
├── governance*            (required)
│   └── GovernanceMetadata
│       ├── license
│       ├── data_sensitivity
│       ├── access_scope
│       ├── is_pii
│       ├── is_phi
│       ├── data_steward
│       ├── data_owner
│       ├── is_external_reference
│       └── embargoed_until
│
├── data_quality
│   └── DataQualityChecks
│       ├── checks_passed
│       ├── checks_failed
│       └── checks_skipped
│
└── metadata*              (required)
    └── DatasetMetadata
        ├── experiment
        │   └── ExperimentMetadata
        │       ├── sub_modality
        │       ├── machine_information    (dict)
        │       ├── experimental_protocols (dict)
        │       └── assay[]
        │           └── OntologyEntry { label, ontology_id }
        │
        ├── sample
        │   └── SampleMetadata
        │       ├── perturbation           (list[dict])
        │       ├── sample_parent          (dict)
        │       ├── sample_preparation_protocols (dict)
        │       ├── organism[]             → OntologyEntry
        │       ├── tissue[]               → TissueEntry { label, ontology_id, type }
        │       ├── development_stage[]    → OntologyEntry
        │       └── disease[]              → OntologyEntry
        │
        └── data_summary
            └── DataSummaryMetadata
                ├── cell_count
                ├── read_count
                ├── read_length
                ├── read_confidence
                ├── dimension
                ├── well
                ├── fov
                ├── dca_schema_version
                ├── resolution
                │   └── ResolutionMetadata { spatial, temporal }
                ├── channels[]
                │   └── ChannelMetadata
                │       ├── name
                │       ├── index
                │       ├── description
                │       ├── channel_type
                │       └── biological_annotation
                │           └── BiologicalAnnotation
                │               ├── biological_target
                │               ├── marker_type
                │               ├── marker
                │               ├── cpg_labeled_structure
                │               └── cpg_labeled_molecule
                └── channel_normalization
                    └── ChannelNormalization
                        ├── dataset_statistics    → IntensityStatistics
                        └── timepoint_statistics  → dict[str, IntensityStatistics]
```

`*` = required field
