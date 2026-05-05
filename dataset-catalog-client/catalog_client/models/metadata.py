"""Biological metadata models: sample, experiment, data summary."""

from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OntologyEntry(BaseModel):
    """{ label, ontology_id } — used for organism, disease, development_stage."""

    label: str | None = Field(
        default=None, description="Human-readable name or label for the ontology term"
    )
    ontology_id: str | None = Field(
        default=None,
        description="Unique identifier from the relevant ontology (e.g., GO:0001234, NCBI:9606)",
    )


class TissueEntry(OntologyEntry):
    """Extends OntologyEntry with optional tissue type."""

    type: str | None = Field(
        default=None,
        description="Additional tissue type classification (e.g., 'organelle', 'cell line', 'tissue', 'cell culture', 'organoid')",
    )


class SampleMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    organism: list[OntologyEntry] | None = Field(
        default=None, description="Organism(s) from which the sample was derived"
    )
    tissue: list[TissueEntry] | None = Field(
        default=None, description="Tissue(s) from which the sample was derived"
    )
    development_stage: list[OntologyEntry] | None = Field(
        default=None, description="Developmental stage(s) of the sample"
    )
    disease: list[OntologyEntry] | None = Field(
        default=None,
        description="Disease(s) or pathological condition(s) associated with the sample",
    )
    perturbation: list[dict[str, Any]] | None = Field(
        default=None, description="Experimental perturbations applied to the sample"
    )
    sample_parent: dict[str, Any] | None = Field(
        default=None, description="Information about the parent sample or source"
    )
    sample_preparation_protocols: dict[str, Any] | None = Field(
        default=None, description="Protocols used for sample preparation and processing"
    )


class ExperimentMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    sub_modality: str | None = Field(
        default=None, description="Specific sub-type within the main data modality"
    )
    assay: list[OntologyEntry] | None = Field(
        default=None, description="Assay(s) or experimental technique(s) used"
    )
    machine_information: dict[str, Any] | None = Field(
        default=None, description="Information about instruments or machines used"
    )
    experimental_protocols: dict[str, Any] | None = Field(
        default=None, description="Protocols and procedures used in the experiment"
    )


class ResolutionMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    spatial: dict[str, Any] | None = Field(
        default=None, description="Spatial resolution information"
    )
    temporal: dict[str, Any] | None = Field(
        default=None, description="Temporal resolution information"
    )


class ChannelType(str, enum.Enum):
    fluorescence = "fluorescence"
    chromogenic = "chromogenic"
    labelfree = "labelfree"
    predicted = "predicted"


class MarkerType(str, enum.Enum):
    endogenous_tag = "endogenous_tag"
    live_cell_dye = "live_cell_dye"
    fixed_dye = "fixed_dye"
    antibody = "antibody"


class BiologicalAnnotation(BaseModel):
    model_config = ConfigDict(extra="allow")

    biological_target: str | None = Field(default=None)
    marker_type: MarkerType | None = Field(default=None)
    marker: str | None = Field(default=None)
    cpg_labeled_structure: str | None = Field(default=None)
    cpg_labeled_molecule: str | None = Field(default=None)


class ChannelMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = Field(default=None)
    index: int | None = Field(default=None)
    description: str | None = Field(default=None)
    channel_type: ChannelType | None = Field(default=None)
    biological_annotation: BiologicalAnnotation | None = Field(default=None)


class IntensityStatistics(BaseModel):
    model_config = ConfigDict(extra="allow")

    p1: float | None = Field(default=None)
    p5: float | None = Field(default=None)
    p95: float | None = Field(default=None)
    p99: float | None = Field(default=None)
    p95_p5: float | None = Field(default=None)
    p99_p1: float | None = Field(default=None)
    mean: float | None = Field(default=None)
    std: float | None = Field(default=None)
    median: float | None = Field(default=None)
    iqr: float | None = Field(default=None)


class ChannelNormalization(BaseModel):
    model_config = ConfigDict(extra="allow")

    dataset_statistics: IntensityStatistics | None = Field(default=None)
    timepoint_statistics: dict[str, IntensityStatistics] | None = Field(default=None)


class DataSummaryMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    cell_count: int | None = Field(default=None)
    read_count: int | None = Field(
        default=None, description="Number of reads or sequences (for sequencing data)"
    )
    read_length: int | None = Field(
        default=None, description="Length of reads in base pairs (for sequencing data)"
    )
    read_confidence: float | None = Field(
        default=None, description="Quality score or confidence measure for reads"
    )
    resolution: ResolutionMetadata | None = Field(
        default=None,
        description="Resolution information for imaging data",
    )
    dimension: list[int] | None = Field(
        default=None,
        description="Dimensional measurements (e.g., [width, height, depth])",
    )
    well: str | None = Field(
        default=None, description="Well identifier for plate-based experiments"
    )
    fov: str | None = Field(
        default=None, description="Field of view identifier for imaging experiments"
    )
    channels: list[ChannelMetadata] | None = Field(
        default=None, description="Channel information for multi-channel imaging data"
    )
    channel_normalization: ChannelNormalization | None = Field(default=None)
    dca_schema_version: str | None = Field(default=None)


class DatasetMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    experiment: ExperimentMetadata | None = Field(
        default=None, description="Experimental design and protocol metadata"
    )
    sample: SampleMetadata | None = Field(
        default=None,
        description="Biological sample characteristics and preparation metadata",
    )
    data_summary: DataSummaryMetadata | None = Field(
        default=None, description="Summary statistics and characteristics of the data"
    )
