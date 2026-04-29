"""RegistrationRequest dataclass and LineageSpec."""

from __future__ import annotations

from dataclasses import dataclass, field

from catalog_client.models.asset import DataAssetRequest
from catalog_client.models.dataset import (
    DatasetModality,
    DatasetRef,
    DatasetRequest,
    DatasetType,
)
from catalog_client.models.governance import GovernanceMetadata
from catalog_client.models.lineage import LineageType
from catalog_client.models.metadata import DatasetMetadata
from catalog_client.models.quality import DataQualityChecks


@dataclass
class LineageSpec:
    """Specifies a lineage relationship for a dataset being registered.

    Supply exactly one of:
    - source_dataset_id: the UUID of the source dataset (option A)
    - source_ref: a DatasetRef that will be resolved to a UUID (option B)
    Leave both None to create a dataset with no lineage (option C).
    """

    lineage_type: LineageType
    source_dataset_id: str | None = None
    source_ref: DatasetRef | None = None


@dataclass
class RegistrationRequest:
    """All inputs needed to register a new biological dataset.

    Pass directly to CatalogClient.register() or construct with
    CatalogClient.new_registration() builder.
    """

    # Required
    canonical_id: str
    name: str
    version: str
    project: str
    modality: DatasetModality
    locations: list[DataAssetRequest]
    governance: GovernanceMetadata
    metadata: DatasetMetadata

    # Optional
    description: str | None = None
    dataset_type: DatasetType | None = None
    data_quality: DataQualityChecks | None = None
    is_latest: bool = True
    lineage: list[LineageSpec] = field(default_factory=list)

    def to_dataset_request(self) -> DatasetRequest:
        return DatasetRequest(
            canonical_id=self.canonical_id,
            name=self.name,
            version=self.version,
            project=self.project,
            modality=self.modality,
            locations=self.locations,
            governance=self.governance,
            metadata=self.metadata,
            description=self.description,
            dataset_type=self.dataset_type,
            data_quality=self.data_quality,
            is_latest=self.is_latest,
        )
