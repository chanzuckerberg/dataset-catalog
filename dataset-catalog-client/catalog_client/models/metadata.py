"""Biological metadata models: sample, experiment, data summary."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OntologyEntry(BaseModel):
    """{ label, ontology_id } — used for organism, disease, development_stage."""

    model_config = ConfigDict(extra="allow")

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
        default=None,
        description="Spatial resolution per axis using OME-ngff v0.5 units (e.g., {'x': 0.1, 'y': 0.1, 'z': 0.25, 'unit': 'micrometer'})",
    )
    temporal: dict[str, Any] | None = Field(
        default=None,
        description="Temporal resolution using OME-ngff v0.5 units (e.g., {'interval': 5, 'unit': 'second'})",
    )


class BiologicalAnnotation(BaseModel):
    model_config = ConfigDict(extra="allow")

    biological_target: str | None = Field(
        default=None,
        description="Target organelle, structure, or protein class visualized (e.g. 'chaperones', 'actin filament', 'nuclei')",
    )
    marker_type: str | None = Field(
        default=None,
        description=(
            "Type of reagent used to label the target; SHOULD be one of: "
            "endogenous_tag (genetically encoded fluorescent protein), "
            "live_cell_dye (cell-permeable dye applied to living cells), "
            "fixed_dye (dye applied after fixation), "
            "antibody (fluorescently conjugated antibody). "
            "SHOULD be provided for fluorescent channels."
        ),
    )
    marker: str | None = Field(
        default=None,
        description="Specific reagent, protein, or dye used (e.g. 'HSPA1B', 'FastAct_SPY555 Live Cell Dye', 'virtual stain')",
    )
    cpg_labeled_structure: str | None = Field(
        default=None,
        description="The cellular compartment or structure made visible; SHOULD match the Label_Structure field from the CellPainting Gallery harmonized ontology",
    )
    cpg_labeled_molecule: str | None = Field(
        default=None,
        description="The specific molecule the reagent binds; SHOULD match the Label_Molecule field from the CellPainting Gallery harmonized ontology",
    )


class ChannelMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = Field(
        default=None,
        description="Short name capturing the acquisition and/or biological context (e.g. 'H2B-GFP', 'Phase2D'); SHOULD match the OME-NGFF omero.channels label",
    )
    index: int | None = Field(
        default=None,
        description="Zero-based channel index in the C axis",
    )
    description: str | None = Field(
        default=None,
        description="Rich natural language description of the channel suitable for text embedding; SHOULD capture biological target and imaging context",
    )
    channel_type: str | None = Field(
        default=None,
        description=(
            "Functional type of the channel; SHOULD be one of: "
            "fluorescence (fluorescent label microscopy), "
            "chromogenic (chromogenic staining e.g. H&E, IHC), "
            "labelfree (brightfield, phase, DIC), "
            "predicted (computationally predicted via virtual staining)"
        ),
    )
    biological_annotation: BiologicalAnnotation | None = Field(
        default=None,
        description="Biological target details for the channel; SHOULD be provided for fluorescence and predicted channels",
    )


class IntensityStatistics(BaseModel):
    model_config = ConfigDict(extra="allow")

    p1: float | None = Field(
        default=None, description="1st percentile of pixel intensities"
    )
    p5: float | None = Field(
        default=None, description="5th percentile of pixel intensities"
    )
    p95: float | None = Field(
        default=None, description="95th percentile of pixel intensities"
    )
    p99: float | None = Field(
        default=None, description="99th percentile of pixel intensities"
    )
    p95_p5: float | None = Field(
        default=None,
        description="Robust range: 95th percentile minus 5th percentile",
    )
    p99_p1: float | None = Field(
        default=None,
        description="Wide robust range: 99th percentile minus 1st percentile",
    )
    mean: float | None = Field(
        default=None, description="Arithmetic mean of pixel intensities"
    )
    std: float | None = Field(
        default=None, description="Standard deviation of pixel intensities"
    )
    median: float | None = Field(
        default=None, description="Median (50th percentile) of pixel intensities"
    )
    iqr: float | None = Field(
        default=None,
        description="Interquartile range (75th percentile minus 25th percentile)",
    )


class ChannelNormalization(BaseModel):
    model_config = ConfigDict(extra="allow")

    dataset_statistics: IntensityStatistics | None = Field(
        default=None,
        description="Intensity statistics computed over all spatial dimensions and timepoints for that channel; MUST be present for each channel normalization entry",
    )
    timepoint_statistics: dict[str, IntensityStatistics] | None = Field(
        default=None,
        description="Per-timepoint intensity statistics keyed by zero-based timepoint index (as string); if present, MUST contain entries for all timepoints in the dataset",
    )


class DataSummaryMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    cell_count: int | None = Field(
        default=None,
        description="Total number of cells detected or segmented in the dataset",
    )
    read_count: int | None = Field(
        default=None, description="Number of reads or sequences (for sequencing data)"
    )
    read_length: int | dict[str, int] | None = Field(
        default=None, description="Length of reads in base pairs (for sequencing data)"
    )
    read_confidence: float | None = Field(
        default=None, description="Quality score or confidence measure for reads"
    )

    # Imaging
    axes: list[dict[str, str]] | None = Field(
        default=None,
        description="OME-ngff v0.5 axes metadata; length MUST equal the number of array dimensions; each entry has 'name', 'type', and 'unit' keys; units MUST follow OME-ngff v0.5 specification for spatial and temporal dimensions",
    )
    channels: list[ChannelMetadata] | None = Field(
        default=None,
        description="DCA per-channel metadata array (dca.channels); SHOULD include an entry for each channel in the image",
    )
    resolution: ResolutionMetadata | None = Field(
        default=None,
        description="Spatial and temporal resolution of the imaging data using OME-ngff v0.5 units",
    )
    dimension: list[int] | None = Field(
        default=None,
        description="Shape of the 5D image array in (time, channels, z, y, x) order; all datasets MUST be 5-dimensional with placeholder values where a dimension is unused",
    )
    multiscales: dict[str, Any] | None = Field(
        default=None,
        description="OME-ngff v0.5 multiscales metadata stored in zarr.json at the group level; includes pyramid levels, coordinate transforms, and MUST document the downsampling method used",
    )
    plate: str | dict[str, Any] | None = Field(
        default=None,
        description="Plate metadata for OME-ngff v0.5 HCS layout; SHOULD follow OME-ngff 0.5 standards for high-content screening datasets",
    )
    well: str | dict[str, Any] | None = Field(
        default=None,
        description="Well metadata for OME-ngff v0.5 HCS layout; SHOULD follow OME-ngff 0.5 standards for high-content screening datasets",
    )
    fov: str | dict[str, Any] | None = Field(
        default=None,
        description="Field-of-view level identifier in an OME-ngff HCS layout (e.g. plate.ome.zarr/A/3/0); the level at which DCA metadata (dca key) is stored in zarr.json",
    )
    channel_normalization: ChannelNormalization | None = Field(
        default=None,
        description="Per-channel normalization statistics stored in dca.normalization_statistics; keyed by zero-based channel index (as string); used for display scaling and AI model training normalization",
    )
    dca_schema_version: str | None = Field(
        default=None,
        description="Version of the DCA (Dynamic Cell Atlas) array specification used (e.g. '0.2'); stored as the version field in the dca object in zarr.json",
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
