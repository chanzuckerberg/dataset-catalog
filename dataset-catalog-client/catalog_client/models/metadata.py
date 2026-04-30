"""Biological metadata models: sample, experiment, data summary."""

from __future__ import annotations

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


class DataSummaryMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    read_count: int | None = Field(
        default=None, description="Number of reads or sequences (for sequencing data)"
    )
    read_length: int | None = Field(
        default=None, description="Length of reads in base pairs (for sequencing data)"
    )
    read_confidence: float | None = Field(
        default=None, description="Quality score or confidence measure for reads"
    )
    resolution: list[int] | None = Field(
        default=None,
        description="Resolution values for imaging data (e.g., [x_res, y_res, z_res])",
    )
    dimension: list[int] | None = Field(
        default=None,
        description="Dimensional measurements (e.g., [width, height, depth])",
    )
    channels: dict[str, Any] | None = Field(
        default=None, description="Channel information for multi-channel imaging data"
    )
    well: str | None = Field(
        default=None, description="Well identifier for plate-based experiments"
    )
    fov: str | None = Field(
        default=None, description="Field of view identifier for imaging experiments"
    )


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
