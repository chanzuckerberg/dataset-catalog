"""Dataset models and DatasetRef identifier."""
from __future__ import annotations

import datetime
import enum
from typing import TYPE_CHECKING, Any, NamedTuple

from pydantic import BaseModel, Field

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


class DatasetCreate(BaseModel):
    canonical_id: str
    name: str
    version: str
    project: str
    modality: DatasetModality
    locations: list[DataAssetRequest] = Field(min_length=1)
    governance: GovernanceMetadata
    metadata: DatasetMetadata
    description: str | None = None
    doi: str | None = None
    cross_db_references: str | None = None
    dataset_type: DatasetType | None = None
    is_latest: bool = False
    record_schema_version: str | None = None
    metadata_schema: str | None = None
    data_quality: DataQualityChecks | None = None


class DatasetResponse(BaseModel):
    id: str
    tombstoned: bool
    created_at: datetime.datetime
    created_by: str | None
    last_modified_at: datetime.datetime
    modified_by: str | None
    canonical_id: str
    version: str
    project: str | None = None
    locations: list[DataAssetResponse] = Field(default_factory=list)
    name: str
    description: str | None = None
    modality: str
    doi: str | None = None
    cross_db_references: str | None = None
    dataset_type: str | None
    is_latest: bool = False
    record_schema_version: str | None = None
    metadata_schema: str | None = None
    governance: dict[str, Any]
    data_quality: dict[str, Any] | None = None
    dataset_metadata: dict[str, Any]
    record_version: int


class DatasetWithRelationsResponse(DatasetResponse):
    """DatasetResponse extended with optional sideloaded relations."""
    incoming_lineage: list[LineageEdgeResponse] | None = None
    outgoing_lineage: list[LineageEdgeResponse] | None = None
    collections: list[CollectionResponse] | None = None


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
