---
name: concepts
description: Explains what the Scientific Dataset Catalog is and how its records relate — datasets, assets (locations), lineage edges and types, collections versus the project field — and decides what should be one dataset. Use when someone asks "what is a dataset/collection/lineage?", "should these files be one dataset or many?", "collection or project?", or how reprocessing, versioning, and updates affect records.
model: sonnet
---

# Catalog concepts

The Scientific Dataset Catalog is a registry of scientific data: it records **what** a dataset is,
**where** its bytes live, **how** it was derived, and **who** may use it. It does not store or
move data; the bytes stay in S3, on HPC, or wherever they already are. Use it to find data, to
cite exact inputs, and to trace a result back to its raw source.

Field definitions live in the `field-reference` skill. This skill explains the objects.

## The four records

| Record | What it is | Identity |
|---|---|---|
| Dataset | One versioned, coherent unit of data with one modality and one governance decision | `canonical_id` + `version` + `project` (the *signature*) |
| Asset (location) | A file or folder holding some of a dataset's bytes; belongs to exactly one dataset | Managed inline in the dataset's `locations` list |
| Lineage edge | An immutable, directed link from a source (parent) dataset to a destination (derived) dataset | System id; one edge per relationship |
| Collection | A mutable, named grouping of datasets and child collections | `canonical_id` + `version` |

Records are never physically deleted. Deleting tombstones a record; tombstoned records drop out of
every list and get. Changing a signature field tombstones the record and creates a new one with a
new id, which preserves history.

## Is this a dataset?

A dataset is the smallest unit that someone would find, cite, grant access to, or derive from **as a
whole**. Ask, in order:

1. **Would anyone use part of it without the rest?** If yes, it is more than one dataset.
2. **Does it have one modality and one processing stage?** Raw and processed data are separate
   datasets linked by lineage, never one record.
3. **Does one governance decision cover all of it?** Mixed consent or licensing means separate datasets.
4. **Is it produced together and versioned together?** If parts are re-run on different schedules, split them.

| Situation | Model it as | Why |
|---|---|---|
| 40 FASTQ files from one sequencing run | One dataset, one folder asset (or 40 file assets) | Used, versioned, and governed together |
| The count matrix computed from those FASTQs | A second dataset (`processed`), lineage `transformed_from` the run | Different stage; raw stays untouched |
| One file per sample, samples analysed independently | One dataset per sample | Each is found and cited on its own |
| One file per sample, only ever analysed as a cohort | One dataset, one asset per file | The cohort is the unit of use |
| A folder of 1,000 images from one plate | One dataset, one folder asset with `file_count` | Files are not individually meaningful |
| An OME-Zarr screen | Ask: screen, plate, well, or FOV? Pick the level people use; assets can point one level down (e.g. one asset per well) | Granularity is the user's decision, not the file layout's |
| QC report about a dataset | Not a dataset: `data_quality` on the dataset it describes | It has no use apart from its subject |

Counterexamples: a dataset is **not** a project, a lab, a pipeline, or "everything in this bucket".

## Assets

Each dataset has at least one asset. An asset is a file or a folder at one storage location
(`s3`, one of the HPC sites, an internal platform, or `external`). Prefer one folder asset over
thousands of file assets when the files are only meaningful together. A dataset copied to a second
location is a separate dataset linked `copy_of`, not a second asset.

## Lineage

Edges point from the parent (`source`) to the derived record (`destination`). Both datasets must
exist before an edge can be created. Edges are immutable: to change one, delete it and create
another.

| Type | Use when |
|---|---|
| `transformed_from` | The destination was produced by processing the source (alignment, segmentation, aggregation) |
| `version_of` | The destination is a re-run or new release of the same data or the same processing |
| `copy_of` | The destination holds the same bytes at another location |

**Reprocessed data is a new record.** Re-running a pipeline with different parameters or code makes a
new dataset linked `transformed_from` its input; a re-run of the same processing (new release of the
same output) is linked `version_of` the previous output. The parent record is never mutated to
describe its children.

**Updates and versions.** Updating a dataset in place keeps its id, so its edges still apply.
Changing a signature field (for example a new `version`) creates a new record with a new id. Do not
assume edges move to the new record: check with `catalog lineage <id>` (search skill) and link the
new record explicitly.

## Collections versus `project`

| Need | Use |
|---|---|
| Name the initiative a dataset belongs to; one value per dataset; part of its identity | `project` |
| Group datasets for a paper, a training set, a study, or an experiment; a dataset can be in many | Collection |
| Group across projects | Collection |
| Membership changes over time | Collection (mutable) |

Collections hold datasets and child collections, so they nest; walk upward with the parents route
(search skill). Never place a collection inside one of its own descendants. Membership is added only
after the dataset exists. Size and depth limits are set by the API and can change: read them from the
API or its errors, never from memory.

## Next

- Field meanings and allowed values: `field-reference`.
- Turning this into a registration: `registration-script`.
- Finding existing records: `search`.
