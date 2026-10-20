# Schema Changelog

This document tracks changes to the catalog schema across versions. Use it as a
reference when migrating datasets registered under an older schema version.

The active schema version is recorded on each dataset record as `record_schema_version`.

## Version summary

| Version | Status |
|---------|--------|
| [v1.6.0](#v160--current) | **Current** — active, default for new registrations |
| [v1.5.0](#v150) | Supported for read |
| [v1.4.0](#v140) | Supported for read |
| [v1.3.0](#v130) | Supported for read |
| [v1.2.0](#v120) | Supported for read |
| [v1.1.0](#v110) | Supported for read |
| [v1.0.0](#v100) | Legacy — read only |

---

## v1.6.0 — Current

**Status:** Active. All new registrations default to this version. See
[`v1.6.0/schema.md`](v1.6.0/schema.md).

### Added

- **Governance:** `data_generator` — who produced the data (the lab, team or pipeline
  behind it), so a consumer with a question about how it was generated knows who to ask.
  Accepts a single name or a list when several parties generated it; the shape it was
  written in is the shape it reads back in, never coerced to the other. Indexed as an
  analyzed text field, so free-text search matches a word inside it rather than only the
  whole value.
- **Collection:** `collection_type` now accepts `study` and `experiment`, alongside
  `publication` and `training`. The first two levels of the recommended
  Study > Experiment > Run hierarchy can now be recorded on the record instead of being
  inferred from its `name`. There is no `run` value — that level stays a name-only label.

### Changed

**Both sensitivity flags are now required on create and update.** A request whose
`governance` omits either is rejected with a `422`, and `null` no longer satisfies them.

- **Governance:** `is_pii` and `is_phi` are now required. A writer that previously left
  them unset must declare a boolean. "I am not sure" is not `false`: the flags decide
  whether a consumer is permitted to open the data at all, so an unknown case belongs
  with the data steward before the record is written.
- **Dataset:** `project` is now non-null on responses too. It has been required on write
  since v1.5.0 and no record predating that remains, so a read no longer has to tolerate
  a missing one. The database column stays nullable; tightening it is a separate change.
- **Dataset:** `record_schema_version` now defaults to `v1.6.0`.

Unlike the v1.5.0 additions, the sensitivity flags are required **on read as well**. No
stored record is missing either, so a response that lacks one is a defect and fails
loudly rather than being served as a record whose sensitivity cannot be determined. The
one governance field that stays nullable on read is `data_steward` — it became required
in v1.5.0 and earlier records were never counted.

Clarified, with no behaviour change: `access_scope` is not validated against
`internal` / `public`. A typo is stored as written and silently drops the record out of
the filter — the v1.5.0 document said it was "accepted and lowercased" without saying it
is never checked.

---

## v1.5.0

**Status:** Supported for read. New registrations should use v1.6.0. See
[`v1.5.0/schema.md`](v1.5.0/schema.md).

### Added

- **Data Asset:** `storage_platform` now accepts `atoll` (CoreWeave cluster storage,
  alongside `reef` and `kelp`).
- **Dataset:** `modality` now accepts `text`.
- **Data quality:** new `report_assets` and `metrics_assets` (each a list of
  `{ name, uri }` pointers to QC reports and metric files) and `metrics` (a list of
  inline `{ name, value }` entries for the handful worth reading without opening a file).

### Changed

Three previously-optional fields are now **required on create and update**. A request
missing any of them is rejected with a `422`.

- **Dataset:** `project` is now required. It is part of the signature
  (`canonical_id`, `version`, `project`), and a NULL in it defeated the
  `canonical_id` + `version` uniqueness constraint — Postgres treats NULLs as
  distinct, so the same pair could be registered repeatedly as long as no project
  was named.
- **Governance:** `data_steward` is now required.
- **Data Asset:** `storage_platform` is now required on **every** entry in
  `locations`, and is no longer derived from the `location_uri` scheme. The
  `s3://` / `gs://` inference that v1.4.0 applied is gone, so an `s3://` location
  that omits it is rejected like any other.

Stored records are unaffected and still read back: both columns stay nullable, and the
response models keep `project` and `storage_platform` nullable, so a legacy row does not
fail response validation.

- **Dataset:** `record_schema_version` now defaults to `v1.5.0`.

### Removed

Dropped from the *declared* schema. All three models set `extra="allow"`, so existing
records keep these keys and callers may still submit them — they are simply no longer
part of the documented schema.

- **Data summary:** `dca_schema_version`. Record the applicable schema in the dataset's
  `metadata_schema` list instead.
- **Channels:** `BiologicalAnnotation.cpg_labeled_structure` and
  `cpg_labeled_molecule`. Use `biological_target` and `marker`.

### Clarified (no behaviour change)

These were already true in v1.4.0; the v1.4.0 document described them imprecisely.

- **Dataset:** `version` is optional on write and defaults to `1.0.0` — it has carried
  that default since v1.4.0, despite being a signature field. The v1.4.0 table's
  *Required* column omitted the default.
- **Collection:** membership entries carry their own `metadata` and are discriminated by
  `entry_type` (`dataset` / `collection`); the 4-level depth limit is a modelling
  convention, not an enforced constraint. Cycles are rejected at write time with a `400`.

---

## v1.4.0

**Status:** Supported for read. New registrations should use v1.6.0. See
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

**Status:** Supported for read. New registrations should use v1.6.0.

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

**Status:** Supported for read. New registrations should use v1.6.0.

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

**Status:** Supported for read. New registrations should use v1.6.0.

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

**Three previously-optional fields are now required.** A payload omitting any of them is
rejected with a `422`. Backfill all three before upgrading:

- `project` on the dataset — part of the signature, so supplying it where it was
  previously NULL changes the signature and forks the record.
- `governance.data_steward`.
- `storage_platform` on **every** entry in `locations`. If you relied on the `s3://` /
  `gs://` inference, you must now pass it explicitly; that inference is gone.

Reads are unaffected — legacy rows with a NULL `project` or `storage_platform` still
parse, because the response models keep both nullable.

Optional work:

- Populate `data_quality.report_assets`, `metrics_assets`, and `metrics` where QC output
  exists.
- Move any `data_summary.dca_schema_version` value into the dataset's `metadata_schema`
  list, and fold `cpg_labeled_structure` / `cpg_labeled_molecule` into
  `biological_target` and `marker`. Both are dropped from the declared schema but still
  accepted, so this is a tidying step rather than a fix.
- `atoll` is available for CoreWeave cluster storage, and `text` for `modality`.

Nothing else changed. If you are comparing the v1.4.0 and v1.5.0 documents directly, see
[Clarified (no behaviour change)](#clarified-no-behaviour-change) — some rows differ
because the v1.4.0 document was imprecise, not because the schema moved.

### v1.5.0 → v1.6.0

**`governance.is_pii` and `governance.is_phi` are now required.** A payload omitting
either is rejected with a `422`, and passing `null` does not satisfy them. Any writer
that left them unset must now declare a boolean for both. Do not reach for `false` to
get past the validator — confirm the real answer with the data steward first.

Reads tighten rather than loosen, which is the reverse of v1.5.0: both flags are
required on responses too, so a record that somehow lacks one raises instead of parsing.
No stored record is missing either, so this surfaces defects, not legacy rows.
`governance.data_steward` is still nullable on read.

`project` is now non-null on responses. Code that defensively handled a missing
`project` on a read can drop that branch; nothing needs backfilling, since the records
that could carry none predate v1.5.0 and no longer exist.

Optional work:

- Populate `governance.data_generator` where the producing lab, team or pipeline is
  known. It is free-text searchable, so it is worth filling in even when it duplicates
  `data_steward`.
- Set `collection_type` to `study` or `experiment` on collections that sit at those
  levels of the hierarchy, instead of encoding the level only in `name`.

Nothing else changed.
