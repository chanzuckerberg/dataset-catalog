"""Dataset models and DatasetRef identifier."""

from __future__ import annotations

import datetime
import enum
import warnings
from typing import TYPE_CHECKING, NamedTuple

from pydantic import BaseModel, Field, field_validator

from catalog_client.models.asset import DataAssetRequest, DataAssetResponse
from catalog_client.models.governance import GovernanceMetadata
from catalog_client.models.metadata import DatasetMetadata
from catalog_client.models.quality import DataQualityChecks

if TYPE_CHECKING:
    from catalog_client.models.collection import CollectionResponse
    from catalog_client.models.lineage import LineageEdgeResponse


class DatasetModality(str, enum.Enum):
    imaging = "imaging"
    sequencing = "sequencing"
    mass_spec = "mass spec"
    unknown = "unknown"


class DatasetType(str, enum.Enum):
    raw = "raw"
    processed = "processed"


class DatasetRef(NamedTuple):
    """Identifies a dataset by its human-readable coordinates."""

    canonical_id: str
    version: str
    project: str

    def __repr__(self) -> str:
        return f"DatasetRef<canonical_id={self.canonical_id},version={self.version},project={self.project}>"


class DatasetRequest(BaseModel):
    canonical_id: str = Field(
        description="Unique identifier for the dataset across versions in a project"
    )
    name: str = Field(description="Human-readable name of the dataset")
    version: str = Field(
        default="1.0.0",
        description="Version string for the dataset (defaults to '1.0.0')",
    )
    project: str | None = Field(
        description="Initiative that this dataset belongs to ex: CellXGene, SRA, CryoET, Shrimp, DynaCell",
    )
    modality: DatasetModality = Field(
        description="Data modality (imaging, sequencing, mass spec, or unknown)"
    )
    locations: list[DataAssetRequest] = Field(
        min_length=1, description="List of data assets that comprise this dataset"
    )
    governance: GovernanceMetadata = Field(
        description="Access control and compliance metadata"
    )
    metadata: DatasetMetadata = Field(
        description="Biological, experimental and data quality metadata"
    )
    description: str | None = Field(
        default=None, description="Detailed description of the dataset"
    )
    doi: str | None = Field(
        default=None, description="Digital Object Identifier for the dataset"
    )
    cross_db_references: list[str] | str | None = Field(
        default=None, description="References to external databases or systems"
    )
    dataset_type: DatasetType | None = Field(
        default=None, description="Whether dataset is raw or processed"
    )
    is_latest: bool = Field(
        default=True, description="Whether this is the latest version of the dataset"
    )
    metadata_schema: str | None = Field(
        default=None, description="Schema version used for the metadata structure"
    )
    data_quality: DataQualityChecks | None = Field(
        default=None, description="Results of data quality validation checks"
    )

    @field_validator("cross_db_references", mode="before")
    @classmethod
    def convert_cross_db_references_to_string(cls, v):
        """Convert list of cross-db references to string separated by '; '."""
        if isinstance(v, list):
            return "; ".join(v)
        return v


class DatasetCreate(DatasetRequest):
    """Deprecated: Use DatasetRequest instead. This will be removed in a future version."""

    def __init__(self, **data):
        warnings.warn(
            "DatasetCreate is deprecated and will be removed in a future version. "
            "Use DatasetRequest instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(**data)


class DatasetResponse(DatasetRequest):
    id: str = Field(description="Unique system-generated ID for this dataset")
    tombstoned: bool = Field(description="Whether the dataset has been soft-deleted")
    created_at: datetime.datetime = Field(
        description="Timestamp when the dataset was first created"
    )
    last_modified_at: datetime.datetime = Field(
        description="Timestamp when the dataset was last updated"
    )
    locations: list[DataAssetResponse] = Field(
        default_factory=list,
        description="List of data assets that comprise this dataset",
    )
    record_version: int = Field(
        description="Internal version number for tracking changes to the record"
    )

    @field_validator("cross_db_references", mode="before")
    @classmethod
    def convert_cross_db_references_to_list(cls, v):
        """Convert string cross-db references to list by splitting on '; '."""
        if isinstance(v, str) and v:
            return v.split("; ")
        return v


class DatasetWithRelationsResponse(DatasetResponse):
    """DatasetResponse extended with optional sideloaded relations."""

    incoming_lineage: list[LineageEdgeResponse] | None = Field(
        default=None,
        description="Lineage edges where this dataset is the destination (what this dataset was derived from)",
    )
    outgoing_lineage: list[LineageEdgeResponse] | None = Field(
        default=None,
        description="Lineage edges where this dataset is the source (what was derived from this dataset)",
    )
    collections: list[CollectionResponse] | None = Field(
        default=None, description="Collections that contain this dataset"
    )


DatasetWithRelationsResponse.model_rebuild(
    _types_namespace={
        "LineageEdgeResponse": __import__(
            "catalog_client.models.lineage", fromlist=["LineageEdgeResponse"]
        ).LineageEdgeResponse,
        "CollectionResponse": __import__(
            "catalog_client.models.collection", fromlist=["CollectionResponse"]
        ).CollectionResponse,
    }
)
