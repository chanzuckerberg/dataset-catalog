"""Biological metadata models: sample, experiment, data summary."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class OntologyEntry(BaseModel):
    """{ label, ontology_id } — used for organism, disease, development_stage."""

    label: str
    ontology_id: str


class TissueEntry(OntologyEntry):
    """Extends OntologyEntry with optional tissue type."""

    type: str | None = None


class SampleMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    organism: list[OntologyEntry] | None = None
    tissue: list[TissueEntry] | None = None
    development_stage: list[OntologyEntry] | None = None
    disease: list[OntologyEntry] | None = None
    perturbation: list[dict[str, Any]] | None = None
    sample_parent: dict[str, Any] | None = None
    sample_preparation_protocols: dict[str, Any] | None = None


class ExperimentMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    sub_modality: str | None = None
    assay: list[str] | None = None
    assay_ontology_id: list[str] | None = None
    machine_information: dict[str, Any] | None = None
    experimental_protocols: dict[str, Any] | None = None


class DataSummaryMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    read_count: int | None = None
    read_length: int | None = None
    read_confidence: float | None = None
    resolution: list[int] | None = None
    dimension: list[int] | None = None
    channels: dict[str, Any] | None = None
    well: str | None = None
    fov: str | None = None


class DatasetMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    experiment: ExperimentMetadata | None = None
    sample: SampleMetadata | None = None
    data_summary: DataSummaryMetadata | None = None
