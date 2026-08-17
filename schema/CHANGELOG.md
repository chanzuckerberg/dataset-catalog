# Schema Changelog

This document tracks changes to the catalog schema across versions. Use it as a
reference when migrating datasets registered under an older schema version.

The active schema version is recorded on each dataset record as `record_schema_version`.

## Version summary

| Version | Status |
|---------|--------|
| [v1.5.0](#v150--draft) | **Draft** — unreleased, spec ahead of the code |
| [v1.4.0](#v140--current) | **Current** — active, default for new registrations |
| [v1.3.0](#v130) | Supported for read |
| [v1.2.0](#v120) | Supported for read |
| [v1.1.0](#v110) | Supported for read |
| [v1.0.0](#v100) | Legacy — read only |

---

## v1.5.0 — Draft

**Status:** Draft, unreleased. This section documents the planned v1.5.0 changes ahead
of the code landing; new registrations should continue to use v1.4.0 until the client
default changes. See [`v1.5.0/schema.md`](v1.5.0/schema.md).

### Added

- **Dataset:** `modality` accepts a new `spatial tx` value for spatial transcriptomics.
  Pair it with an `experiment.sub_modality` (e.g. `Visium`, `Xenium`, `MERFISH`) for the
  specific platform.
- **Dataset:** `dataset_type` accepts a new `aggregated` value, for datasets assembled
  by combining several existing datasets (e.g. an atlas or a merged cohort) rather than
  by transforming a single upstream run.
- **Dataset:** new optional `publications` field (`list[string]`) for related
  publications, as DOIs or free-text citations. Distinct from `doi`, which identifies
  the dataset itself.
- **Sample metadata:** new optional `cell_strain` field (`list[OntologyEntry]`) for the
  cell line or strain a sample came from. Recommended ontology: **CLO** (e.g.
  `CLO:0003684` for HeLa), or Cellosaurus (`CVCL_` prefix) where CLO has no term.
- **Data quality:** new optional `metrics` field for quantitative quality metrics
  (e.g. `{"completeness": 0.97}`), alongside the existing pass/fail/skip check lists.
- **Dataset:** the response-only `record_version` counter and the audit fields (`id`,
  `created_at`, `last_modified_at`, `tombstoned`) are now documented explicitly.

### Changed

- **Field levels:** field tables now carry a `Level` column — `Required` (enforced by
  the schema), `Recommended` (not enforced, but expected for catalog quality),
  `Optional`, or `Deprecated` — replacing the boolean `Required` column.
- **Governance:** `data_owner` is now **required**. Records without one must supply it
  on the next update.
- **Dataset:** `dataset_type` and `metadata` are now **required** on create and update.
  `locations` must contain at least one asset.
- **Dataset signature:** filling a signature field in from `null` now also tombstones
  the record and inserts a new one. This is stricter than the Data Asset rules, where
  filling a null field remains an in-place change.
- **Dataset versioning:** a version bump now records a `version_of` lineage edge from
  the old record to the new one and carries the old record's active lineage edges
  forward, remapping them to the new record's assets by URI. Registering a new
  `is_latest` record demotes any other `is_latest` record in the same
  (`canonical_id`, `project`) group.
- **Dataset updates:** `record_version` increments only when a value actually changed.
  Updating a tombstoned dataset returns `404`.

### Removed

- **Data summary:** `dca_schema_version` is removed. Record external metadata
  specifications on the dataset's `metadata_schema` list instead.
- **Biological annotation:** `cpg_labeled_structure` and `cpg_labeled_molecule` are
  removed from `ChannelMetadata.biological_annotation`. Record the targeted structure or
  molecule in `biological_target` instead.

### Deprecated

- **Governance:** `data_sensitivity` — still accepted for backward compatibility;
  express public visibility via `access_scope` instead. (v1.4.0 described this field as
  removed; it remains present on the model, so v1.5.0 records it as deprecated.)

---

## v1.4.0 — Current

**Status:** Active. All new registrations default to this version. See
[`v1.4.0/schema.md`](v1.4.0/schema.md).

### Added

- **Data Asset:** `storage_platform` now accepts `globus` as a valid value, and
  `globus://` is recognized as a `location_uri` scheme.
- **Dataset:** `metadata_schema` is now a `list[string]` (previously a single string),
  allowing multiple metadata schemas to apply to one dataset.
- **Data summary:** new imaging fields `axes` (`list[json]` of `{ name, type, unit }`),
  `multiscales`, and `plate` for Zarr/imaging datasets.
- **Lineage Edge:** new optional `metadata` block for recording processing algorithm
  name, pipeline version, transformation parameters, and similar context.
- **Collection:** promoted to a multi-level provenance hierarchy (Study → Experiment →
  Run). `collection_type` now accepts `study`, `experiment`, and `run` in addition to
  `publication`, `training`, and `other`. New optional fields `metadata`, `doi`,
  `license`, and `external_reference`.

### Changed

- **Dataset signature:** `version` and `project` are now **required** (alongside
  `canonical_id`). Updating any signature field tombstones the record, sets
  `is_latest=false`, and creates a new record with an incremented `record_version`.
- **Governance:** access classification is expressed via `access_scope`
  (`public` / `internal`, defaulting to `internal`). The free-form `data_sensitivity`
  field is no longer part of the governance block.
- **Collection:** added explicit constraints — collections may not exceed 4 levels deep,
  and cycles are rejected at write time. A dataset may belong to multiple collection
  types simultaneously.

---

## v1.3.0

**Status:** Supported for read. New registrations should use v1.4.0.

### Added

- `DataSummaryMetadata.channel_normalization` — `ChannelNormalization` block for
  recording per-dataset and per-timepoint intensity statistics across channels.
  - `dataset_statistics` → `IntensityStatistics` (p1, p5, p95, p99, p95_p5, p99_p1,
    mean, std, median, iqr)
  - `timepoint_statistics` → `dict[str, IntensityStatistics]` keyed by zero-based
    timepoint index string; must cover all timepoints if present.
- `ChannelMetadata.biological_annotation` — `BiologicalAnnotation` sub-block per channel.
  - `biological_target`, `marker_type` (endogenous_tag / live_cell_dye / fixed_dye /
    antibody), `marker`, `cpg_labeled_structure`, `cpg_labeled_molecule`
- `DataSummaryMetadata.dca_schema_version` — DCA metadata schema version applied to the
  dataset.

### Changed

- `DataSummaryMetadata.channels` entries now accept the full `ChannelMetadata` shape
  including `biological_annotation`. Previously only `name`, `index`, and `description`
  were supported.

---

## v1.2.0

**Status:** Supported for read. New registrations should use v1.4.0.

### Added

- `DataSummaryMetadata.channels` — list of `ChannelMetadata` entries describing
  per-channel properties.
  - Fields: `name`, `index`, `description`, `channel_type` (fluorescence / chromogenic /
    labelfree / predicted)
- `DataSummaryMetadata.resolution` — `ResolutionMetadata` block with `spatial` and
  `temporal` for imaging datasets.
- `DataSummaryMetadata.fov` — field-of-view ID(s) for spatial/imaging datasets.
- `DataSummaryMetadata.well` — well ID(s) for plate-based experiments.
- `DataSummaryMetadata.dimension` — image dimension array (e.g. `[Z, Y, X]`).
- `GovernanceMetadata.embargoed_until` — ISO 8601 date field for embargoed datasets.

### Changed

- `DataSummaryMetadata.read_length` — now accepts either a plain `integer` or a `dict`
  mapping read lengths to counts (previously integer only).

---

## v1.1.0

**Status:** Supported for read. New registrations should use v1.4.0.

### Added

- `DatasetRequest.data_quality` — optional `DataQualityChecks` block.
  - `checks_passed`, `checks_failed`, `checks_skipped` (all accept any type)
- `DatasetRequest.cross_db_references` — free-text field for external database references.
- `DatasetRequest.doi` — Digital Object Identifier field.
- `GovernanceMetadata.is_external_reference` — flag for datasets that reference external
  sources.
- `SampleMetadata.development_stage` — list of ontology entries for developmental stage.
- `ExperimentMetadata.assay` — list of ontology entries for assay type.
- `DataSummaryMetadata.read_confidence` — mean read quality score.

### Changed

- `GovernanceMetadata.access_scope` — now normalized to lowercase on ingest.
- `tissue` entries — extended with an optional `type` field (e.g. `primary`,
  `cell line`). Previously tissue was a plain ontology entry.

---

## v1.0.0

**Status:** Legacy. Supported for read only.

### Initial schema

First stable release of the dataset schema. Established the core structure:

- **Identity fields:** `canonical_id`, `version`, `project` as signature fields.
- **Display fields:** `name`, `description`, `modality`, `dataset_type`, `is_latest`.
- **Locations:** `locations[]` with `DataAsset` entries (`location_uri`, `asset_type`,
  `encoding`, `size_bytes`, `checksum`, `checksum_alg`, `file_format`,
  `storage_platform`, `file_count`).
- **Governance:** `GovernanceMetadata` with `license`, `access_scope`, `is_pii`,
  `is_phi`, `data_steward`, `data_owner`.
- **Metadata envelope:** `DatasetMetadata` with `experiment` (`sub_modality`,
  `machine_information`, `experimental_protocols`), `sample` (`organism`, `tissue`,
  `disease`, `perturbation`, `sample_parent`, `sample_preparation_protocols`), and
  `data_summary` (`cell_count`, `read_count`, `read_length`).

---

## Migration notes

All schema versions to date are backward compatible: a payload valid under an older
version remains valid under newer ones, with the exception of newly required fields.

### v1.0.0 → v1.1.0

- No breaking changes. Optionally add `data_quality`, `doi`, `cross_db_references`.
- Re-check `access_scope` values — mixed-case values are normalized to lowercase on the
  next update.

### v1.1.0 → v1.2.0

- No breaking changes. For imaging datasets, consider populating `channels`,
  `resolution`, `dimension`, `well`, and `fov` in `data_summary`.
- To record a multi-length read distribution, switch `read_length` to a dict
  (e.g. `{"75": 1200000, "100": 3000000}`).

### v1.2.0 → v1.3.0

- No breaking changes. For imaging datasets with channel data, consider adding
  `biological_annotation` to each `ChannelMetadata` entry.
- If intensity normalization statistics are available, populate `channel_normalization`.
  If `timepoint_statistics` is provided, it must cover every timepoint index present.

### v1.3.0 → v1.4.0

- **`version` and `project` are now required.** Records previously written without them
  must supply both on the next update; doing so changes the signature and creates a new
  record.
- If a single-string `metadata_schema` was used, wrap it in a list.
- For imaging/Zarr datasets, consider populating `axes`, `multiscales`, and `plate`.
- For collections, set `collection_type` to `study` / `experiment` / `run` where the
  provenance hierarchy applies, and populate `external_reference` where an external
  equivalent exists.
- The `data_sensitivity` governance field is dropped; express public visibility via
  `access_scope`.

### v1.4.0 → v1.5.0

- **`governance.data_owner` is now required.** Records without one must supply it on
  the next update. This is a non-signature field, so it is applied in place.
- **`dataset_type` and `metadata` are now required** on create and update. Datasets
  registered without a `dataset_type` must pick `raw`, `processed`, or `aggregated`.
- **Do not fill signature fields in from `null` casually.** Under v1.5.0 that
  tombstones the record and creates a new one (v1.4.0 treated it as an in-place edit).
  Since v1.4.0 already requires `version` and `project`, this mainly affects records
  carried forward from v1.3.0 and earlier.
- **`dca_schema_version` is removed.** Move the value to the dataset's
  `metadata_schema` list, as a URI to the external specification.
- **`cpg_labeled_structure` and `cpg_labeled_molecule` are removed.** Fold the value
  into `biological_annotation.biological_target` on the affected channels.
- Stop populating `data_sensitivity`; it is deprecated. Existing values are retained
  and still readable.
- Optionally add `publications`, `sample.cell_strain`, and `data_quality.metrics`.
- For spatial transcriptomics datasets previously registered as `sequencing` or
  `imaging`, switch `modality` to `spatial tx`. This is a non-signature field, so the
  change applies in place.
- For datasets built by merging several upstream datasets, switch `dataset_type` to
  `aggregated` and record a lineage edge to each contributing dataset.
