"""
Pydantic models mirroring the Catalog API schemas.
"""
from __future__ import annotations

import datetime
import enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from catalog_client._context import get_client

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AssetType(str, enum.Enum):
    file = "file"
    folder = "folder"


class StoragePlatform(str, enum.Enum):
    s3 = "s3"
    bruno_hpc = "bruno hpc"
    hpc = "hpc"
    coreweave = "coreweave"
    external = "external"
    other = "other"


class DatasetModality(str, enum.Enum):
    imaging = "imaging"
    sequencing = "sequencing"
    mass_spec = "mass spec"
    unknown = "unknown"


class DatasetType(str, enum.Enum):
    raw = "raw"
    processed = "processed"


class CollectionType(str, enum.Enum):
    publication = "publication"
    training = "training"


class LineageType(str, enum.Enum):
    version_of = "version_of"
    transformed_from = "transformed_from"
    copy_of = "copy_of"


class TokenExpiry(str, enum.Enum):
    seven_days = "7d"
    thirty_days = "30d"
    ninety_days = "90d"
    infinite = "infinite"


# ---------------------------------------------------------------------------
# Data assets
# ---------------------------------------------------------------------------

class DataAssetRequest(BaseModel):
    location_uri: str
    asset_type: AssetType
    encoding: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    checksum_alg: str | None = None
    file_format: str | None = None
    description: str | None = None
    storage_platform: StoragePlatform | None = None
    file_count: int | None = None
    includes_pattern: str | None = None
    excludes_pattern: str | None = None


class DataAssetResponse(BaseModel):
    id: str
    tombstoned: bool
    created_at: datetime.datetime
    created_by: str | None
    last_modified_at: datetime.datetime
    modified_by: str | None
    location_uri: str
    asset_type: AssetType
    encoding: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    checksum_alg: str | None = None
    file_format: str | None = None
    description: str | None = None
    storage_platform: StoragePlatform | None = None
    file_count: int | None = None
    includes_pattern: str | None = None
    excludes_pattern: str | None = None
    dataset_id: str


# ---------------------------------------------------------------------------
# Governance / metadata
# ---------------------------------------------------------------------------

class GovernanceMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    license: str | None = None
    data_sensitivity: str | None = None
    access_scope: str | None = None
    is_pii: bool | None = None
    is_phi: bool | None = None
    data_steward: str | None = None
    data_owner: str | None = None
    is_external_reference: bool | None = None
    embargoed_until: datetime.date | None = None


class OntologyEntry(BaseModel):
    label: str
    ontology_id: str


class TissueEntry(BaseModel):
    label: str
    ontology_id: str
    type: str | None = None


class ExperimentMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    sub_modality: str | None = None
    assay: list[OntologyEntry] | None = None
    machine_information: dict[str, Any] | None = None
    experimental_protocols: dict[str, Any] | None = None


class SampleMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    organism: list[OntologyEntry] | None = None
    tissue: list[TissueEntry] | None = None
    development_stage: list[OntologyEntry] | None = None
    disease: list[OntologyEntry] | None = None
    perturbation: list[dict[str, Any]] | None = None
    sample_parent: dict[str, Any] | None = None
    sample_preparation_protocols: dict[str, Any] | None = None


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


class DataQualityChecks(BaseModel):
    model_config = ConfigDict(extra="allow")

    checks_passed: list[str] | None = None
    checks_failed: list[str] | None = None
    checks_skipped: list[str] | None = None


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------

class DatasetCreate(BaseModel):
    canonical_id: str
    version: str = "1.0.0"
    modality: DatasetModality
    project: str | None = None
    locations: list[DataAssetRequest] = Field(min_length=1)
    name: str
    description: str | None = None
    doi: str | None = None
    cross_db_references: str | None = None
    dataset_type: DatasetType | None = None
    is_latest: bool = True
    record_schema_version: str | None = None
    metadata_schema: str | None = None
    governance: GovernanceMetadata
    data_quality: DataQualityChecks | None = None
    metadata: DatasetMetadata


class DatasetUpdate(BaseModel):
    """Full replacement update — mirrors DatasetCreate; all required fields must be provided."""

    canonical_id: str
    version: str = "1.0.0"
    modality: DatasetModality
    project: str | None = None
    locations: list[DataAssetRequest] = Field(min_length=1)
    name: str
    description: str | None = None
    doi: str | None = None
    cross_db_references: str | None = None
    dataset_type: DatasetType | None = None
    is_latest: bool = True
    record_schema_version: str | None = None
    metadata_schema: str | None = None
    governance: GovernanceMetadata
    data_quality: DataQualityChecks | None = None
    metadata: DatasetMetadata


class DatasetResponse(BaseModel):
    id: str
    tombstoned: bool
    created_at: datetime.datetime
    created_by: str | None
    last_modified_at: datetime.datetime
    modified_by: str | None
    canonical_id: str
    version: str
    modality: str
    project: str | None = None
    locations: list[DataAssetResponse] = Field(default_factory=list)
    name: str
    description: str | None = None
    doi: str | None = None
    cross_db_references: str | None = None
    dataset_type: str | None
    is_latest: bool = True
    record_schema_version: str | None = None
    metadata_schema: str | None = None
    governance: dict[str, Any]
    data_quality: dict[str, Any] | None = None
    dataset_metadata: dict[str, Any]
    record_version: int


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

class CollectionCreate(BaseModel):
    canonical_id: str
    version: str
    name: str
    description: str | None = None
    license: str | None = None
    doi: str | None = None
    collection_owner: str
    collection_type: CollectionType | None = None
    metadata: dict[str, Any] | None = None


class CollectionUpdate(BaseModel):
    canonical_id: str | None = None
    version: str | None = None
    name: str | None = None
    description: str | None = None
    license: str | None = None
    doi: str | None = None
    collection_owner: str | None = None
    collection_type: CollectionType | None = None
    metadata: dict[str, Any] | None = None


class CollectionResponse(BaseModel):
    id: str
    tombstoned: bool
    created_at: datetime.datetime
    created_by: str | None
    last_modified_at: datetime.datetime
    modified_by: str | None
    canonical_id: str
    version: str
    name: str
    description: str | None = None
    license: str | None = None
    doi: str | None = None
    collection_owner: str
    collection_type: CollectionType | None = None
    collection_metadata: dict[str, Any] | None


# ---------------------------------------------------------------------------
# Lineage
# ---------------------------------------------------------------------------

class LineageEdgeCreate(BaseModel):
    source_dataset_id: str
    destination_dataset_id: str
    source_data_asset_id: str | None = None
    destination_data_asset_id: str | None = None
    lineage_type: LineageType
    metadata: dict[str, Any] | None = None


class LineageEdgeResponse(BaseModel):
    id: str
    tombstoned: bool
    created_at: datetime.datetime
    created_by: str | None
    last_modified_at: datetime.datetime
    modified_by: str | None
    source_dataset_id: str
    destination_dataset_id: str
    source_data_asset_id: str | None = None
    destination_data_asset_id: str | None = None
    lineage_type: LineageType
    lineage_metadata: dict[str, Any] | None

    # Client-side resolved fields — populated by LineageClient.expand()
    source_dataset: DatasetResponse | None = None
    destination_dataset: DatasetResponse | None = None

    def fetch_source_dataset(self) -> DatasetResponse:
        dataset = get_client().datasets.get(self.source_dataset_id)
        self.source_dataset = dataset
        return dataset

    def fetch_destination_dataset(self) -> DatasetResponse:
        dataset = get_client().datasets.get(self.destination_dataset_id)
        self.destination_dataset = dataset
        return dataset

    def fetch_expanded(self) -> LineageEdgeResponse:
        """Fetch and populate source_dataset and destination_dataset. Returns self."""
        result = get_client().lineages.expand([self])[0]
        self.source_dataset = result.source_dataset
        self.destination_dataset = result.destination_dataset
        return self


# ---------------------------------------------------------------------------
# DatasetWithRelationsResponse — returned by GET list/get endpoints
# ---------------------------------------------------------------------------

class DatasetWithRelationsResponse(DatasetResponse):
    """DatasetResponse extended with optional lineage edges and collection memberships."""

    incoming_lineage: list[LineageEdgeResponse] | None = None
    outgoing_lineage: list[LineageEdgeResponse] | None = None
    collections: list[CollectionResponse] | None = None

    def fetch_lineages(
        self, *, lineage_type: LineageType | None = None, limit: int = 10
    ) -> list[LineageEdgeResponse]:
        client = get_client()
        seen: set[str] = set()
        results: list[LineageEdgeResponse] = []
        for edge in client.lineages.list_(
            source_dataset_id=self.id, lineage_type=lineage_type, limit=limit
        ).results:
            if edge.id not in seen:
                seen.add(edge.id)
                results.append(edge)
        for edge in client.lineages.list_(
            destination_dataset_id=self.id, lineage_type=lineage_type, limit=limit
        ).results:
            if edge.id not in seen:
                seen.add(edge.id)
                results.append(edge)
        return results


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class PaginatedResponse(BaseModel, Generic[T]):
    total: int
    limit: int
    offset: int
    results: list[T]


# ---------------------------------------------------------------------------
# Tokens (models only — no client; users must supply their token externally)
# ---------------------------------------------------------------------------

class TokenIssueRequest(BaseModel):
    user_name: str
    user_team: str
    user_email: str
    name: str
    expiry: TokenExpiry = TokenExpiry.ninety_days


class APITokenResponse(BaseModel):
    id: str
    user_id: str
    name: str
    token_prefix: str
    is_active: bool
    expires_at: datetime.datetime | None
    last_used_at: datetime.datetime | None
    created_at: datetime.datetime


class APITokenCreatedResponse(APITokenResponse):
    token: str


class TokenValidateRequest(BaseModel):
    token: str


class TokenUserResponse(BaseModel):
    id: str
    name: str
    team: str
    email: str


class TokenValidateResponse(BaseModel):
    token: APITokenResponse
    user: TokenUserResponse
