# Dataset Model — v1.4.0

> Current as of v1.4.0. For history, see [dataset-model-changelog.md](dataset-model-changelog.md).

---

## `DatasetMetadata`

Top-level metadata envelope with three sub-keys: `experiment`, `sample`, `data_summary`.

---

### `ExperimentMetadata`

| Field | Type |
|---|---|
| `sub_modality` | `str \| None` |
| `assay` | `list[OntologyEntry] \| None` |
| `machine_information` | `dict[str, Any] \| None` |
| `experimental_protocols` | `dict[str, Any] \| None` |

---

### `SampleMetadata`

| Field | Type |
|---|---|
| `organism` | `list[OntologyEntry] \| None` |
| `tissue` | `list[TissueEntry] \| None` |
| `development_stage` | `list[OntologyEntry] \| None` |
| `disease` | `list[OntologyEntry] \| None` |
| `perturbation` | `list[dict[str, Any]] \| None` |
| `sample_parent` | `dict[str, Any] \| None` |
| `sample_preparation_protocols` | `dict[str, Any] \| None` |

`OntologyEntry`: `{ label: str | None, ontology_id: str | None }`

`TissueEntry`: extends `OntologyEntry` with `type: str | None`

---

### `DataSummaryMetadata`

| Field | Type | Notes |
|---|---|---|
| `axes` | `list[dict[str, str]] \| None` | expected keys: `name`, `type`, `unit` |
| `cell_count` | `int \| None` | |
| `read_count` | `int \| None` | |
| `read_length` | `int \| dict[str, int] \| None` | dict maps read length (as string key) to count |
| `read_confidence` | `float \| None` | |
| `resolution` | `ResolutionMetadata \| None` | |
| `multiscales` | `dict[str, Any] \| None` | |
| `dimension` | `list[int] \| None` | |
| `plate` | `str \| dict[str, Any] \| None` | |
| `well` | `str \| dict[str, Any] \| None` | |
| `fov` | `str \| dict[str, Any] \| None` | |
| `channels` | `list[ChannelMetadata] \| None` | |
| `channel_normalization` | `ChannelNormalization \| None` | |
| `dca_schema_version` | `str \| None` | |

---

### `ResolutionMetadata`

| Field | Type |
|---|---|
| `spatial` | `dict \| None` |
| `temporal` | `dict \| None` |

---

### `ChannelMetadata`

| Field | Type |
|---|---|
| `name` | `str \| None` |
| `index` | `int \| None` |
| `description` | `str \| None` |
| `channel_type` | `str \| None` |
| `biological_annotation` | `BiologicalAnnotation \| None` |

---

### `BiologicalAnnotation`

| Field | Type |
|---|---|
| `biological_target` | `str \| None` |
| `marker_type` | `str \| None` |
| `marker` | `str \| None` |
| `cpg_labeled_structure` | `str \| None` |
| `cpg_labeled_molecule` | `str \| None` |

---

### `ChannelNormalization`

| Field | Type |
|---|---|
| `dataset_statistics` | `IntensityStatistics \| None` |
| `timepoint_statistics` | `dict[str, IntensityStatistics] \| None` |

---

### `IntensityStatistics`

| Field | Type |
|---|---|
| `p1` | `float \| None` |
| `p5` | `float \| None` |
| `p95` | `float \| None` |
| `p99` | `float \| None` |
| `p95_p5` | `float \| None` |
| `p99_p1` | `float \| None` |
| `mean` | `float \| None` |
| `std` | `float \| None` |
| `median` | `float \| None` |
| `iqr` | `float \| None` |

---

## `GovernanceMetadata`

| Field | Type | Notes |
|---|---|---|
| `license` | `str \| None` | |
| `data_sensitivity` | `str \| None` | `"Low"`, `"Medium"`, or `"High"` |
| `access_scope` | `str \| None` | `"public"` or `"internal"` |
| `is_pii` | `bool \| None` | |
| `is_phi` | `bool \| None` | |
| `data_steward` | `str \| None` | |
| `data_owner` | `str \| None` | |
| `is_external_reference` | `bool` | default `False` |
| `embargoed_until` | `datetime.date \| None` | |

---

## `DataQualityChecks`

| Field | Type |
|---|---|
| `checks_passed` | `Any \| None` |
| `checks_failed` | `Any \| None` |
| `checks_skipped` | `Any \| None` |

---

## Top-level `Dataset` fields

| Field | Type | Notes |
|---|---|---|
| `canonical_id` | `str` | signature field |
| `version` | `str` | signature field, default `"1.0.0"` |
| `modality` | `DatasetModality` | `imaging`, `sequencing`, `mass spec`, or `unknown` |
| `project` | `str \| None` | signature field |
| `locations` | `list[DataAssetRequest]` | min 1 item, required |
| `name` | `str` | |
| `description` | `str \| None` | |
| `doi` | `str \| None` | |
| `cross_db_references` | `str \| None` | accepts a `list[str]` on input; serialized to a `"; "`-joined string |
| `dataset_type` | `DatasetType \| None` | `"raw"` or `"processed"` |
| `is_latest` | `bool` | default `True` |
| `record_schema_version` | `str` | default `"v1.4.0"` |
| `metadata_schema` | `list[str] \| None` | |
| `governance` | `GovernanceMetadata` | required |
| `data_quality` | `DataQualityChecks \| None` | |
| `metadata` | `DatasetMetadata` | required on create/update |
| `record_version` | `int` | response only; increments on every update |
