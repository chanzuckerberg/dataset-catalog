# Data Model Changelog

This document tracks changes to the `DatasetRequest` schema and related catalog data models across schema versions. Use this as a reference when migrating datasets registered under an older schema version.

The active schema version is recorded on each dataset record as `record_schema_version`.

## Version summary

| Version | Status |
|---------|--------|
| [v1.3.0](#v130--current) | **Current** — active, default for new registrations |
| [v1.2.0](#v120) | Supported for read |
| [v1.1.0](#v110) | Supported for read |
| [v1.0.0](#v100) | Legacy — read only |

---

## v1.3.0 — Current

**Status:** Active. All new registrations default to this version.

### Added

- `DataSummaryMetadata.channel_normalization` — new `ChannelNormalization` block for recording per-dataset and per-timepoint intensity statistics across channels.
  - `dataset_statistics` → `IntensityStatistics` (p1, p5, p95, p99, p95_p5, p99_p1, mean, std, median, iqr)
  - `timepoint_statistics` → `dict[str, IntensityStatistics]` keyed by zero-based timepoint index string; must cover all timepoints if present.
- `ChannelMetadata.biological_annotation` — new `BiologicalAnnotation` sub-block per channel.
  - `biological_target`, `marker_type` (endogenous_tag / live_cell_dye / fixed_dye / antibody), `marker`, `cpg_labeled_structure`, `cpg_labeled_molecule`
- `DataSummaryMetadata.dca_schema_version` — string field to record the DCA metadata schema version applied to this dataset.

### Changed

- `DataSummaryMetadata.channels` entries now accept the full `ChannelMetadata` shape including `biological_annotation`. Previously only `name`, `index`, and `description` were supported.

---

## v1.2.0

**Status:** Supported for read. New registrations should use v1.3.0.

### Added

- `DataSummaryMetadata.channels` — list of `ChannelMetadata` entries describing per-channel properties.
  - Fields: `name`, `index`, `description`, `channel_type` (fluorescence / chromogenic / labelfree / predicted)
- `DataSummaryMetadata.resolution` — new `ResolutionMetadata` block.
  - `spatial` (dict) and `temporal` (dict) for imaging datasets.
- `DataSummaryMetadata.fov` — field-of-view ID(s) for spatial/imaging datasets.
- `DataSummaryMetadata.well` — well ID(s) for plate-based experiments.
- `DataSummaryMetadata.dimension` — image dimension array (e.g. `[Z, Y, X]`).
- `GovernanceMetadata.embargoed_until` — ISO 8601 date field for embargoed datasets.

### Changed

- `DataSummaryMetadata.read_length` — now accepts either a plain `integer` or a `dict` mapping read lengths to counts (previously integer only).

---

## v1.1.0

**Status:** Supported for read. New registrations should use v1.3.0.

### Added

- `DatasetRequest.data_quality` — new optional `DataQualityChecks` block.
  - `checks_passed`, `checks_failed`, `checks_skipped` (all accept any type: count, list of names, etc.)
- `DatasetRequest.cross_db_references` — free-text field for external database references.
- `DatasetRequest.doi` — Digital Object Identifier field.
- `GovernanceMetadata.is_external_reference` — boolean to flag datasets that are references to external sources.
- `SampleMetadata.development_stage` — list of `OntologyEntry` for developmental stage annotation.
- `ExperimentMetadata.assay` — list of `OntologyEntry` for assay type annotation.
- `DataSummaryMetadata.read_confidence` — float field for mean read quality score.

### Changed

- `GovernanceMetadata.access_scope` — now normalized to lowercase on ingest. Previously mixed-case values were stored as-is.
- `TissueEntry` — extended `OntologyEntry` with an optional `type` field (e.g. `primary`, `cell line`). Previously tissue was a plain `OntologyEntry`.

---

## v1.0.0

**Status:** Legacy. Supported for read only.

### Initial schema

First stable release of the `DatasetRequest` schema. Established the core structure:

- **Identity fields:** `canonical_id`, `version`, `project` as signature fields.
- **Display fields:** `name`, `description`, `modality`, `dataset_type`, `is_latest`.
- **Locations:** `locations[]` with `DataAsset` entries (`location_uri`, `asset_type`, `encoding`, `size_bytes`, `checksum`, `checksum_alg`, `file_format`, `storage_platform`, `file_count`).
- **Governance:** `GovernanceMetadata` with `license`, `data_sensitivity`, `access_scope`, `is_pii`, `is_phi`, `data_steward`, `data_owner`.
- **Metadata envelope:** `DatasetMetadata` with `experiment` (`sub_modality`, `machine_information`, `experimental_protocols`), `sample` (`organism`, `tissue`, `disease`, `perturbation`, `sample_parent`, `sample_preparation_protocols`), and `data_summary` (`cell_count`, `read_count`, `read_length`).

---

## Migration notes

### v1.0.0 → v1.1.0

- No breaking changes. All v1.0.0 payloads are valid v1.1.0 payloads.
- Optionally add `data_quality`, `doi`, `cross_db_references` if available.
- Re-check `access_scope` values — any mixed-case values stored under v1.0.0 will be normalized to lowercase on the next update.

### v1.1.0 → v1.2.0

- No breaking changes. All v1.1.0 payloads are valid v1.2.0 payloads.
- For imaging datasets, consider populating `channels`, `resolution`, `dimension`, `well`, and `fov` in `data_summary`.
- If `read_length` is already set as an integer, no change needed. To record a multi-length distribution, switch to a `dict` (e.g. `{"75": 1200000, "100": 3000000}`).

### v1.2.0 → v1.3.0

- No breaking changes. All v1.2.0 payloads are valid v1.3.0 payloads.
- For imaging datasets with channel data, consider adding `biological_annotation` to each `ChannelMetadata` entry.
- If intensity normalization statistics are available, populate `channel_normalization` in `data_summary`.
- If `timepoint_statistics` is provided, it must include an entry for every timepoint index present in the dataset.
