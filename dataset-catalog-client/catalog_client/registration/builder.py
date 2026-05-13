"""RegistrationBuilder — fluent interface for constructing RegistrationRequest."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from catalog_client.models.asset import AssetType, DataAssetRequest, StoragePlatform
from catalog_client.models.dataset import DatasetModality, DatasetRef, DatasetType
from catalog_client.models.governance import GovernanceMetadata
from catalog_client.models.lineage import LineageType
from catalog_client.models.metadata import (
    DatasetMetadata,
    DataSummaryMetadata,
    ExperimentMetadata,
    SampleMetadata,
)
from catalog_client.models.quality import DataQualityChecks
from catalog_client.registration.request import LineageSpec, RegistrationRequest

if TYPE_CHECKING:
    from catalog_client.client.catalog import CatalogClient


class RegistrationBuilder:
    """Fluent builder for RegistrationRequest.

    Obtain via CatalogClient.new_registration(...) rather than instantiating directly.
    """

    def __init__(
        self,
        canonical_id: str,
        name: str,
        version: str,
        project: str,
        modality: DatasetModality,
        *,
        client: CatalogClient | None = None,
    ) -> None:
        self._client = client

        # Initialize with RegistrationRequest containing all required fields
        self._request = RegistrationRequest(
            canonical_id=canonical_id,
            name=name,
            version=version,
            project=project,
            modality=modality,
            locations=[],
            governance=GovernanceMetadata(),
            metadata=DatasetMetadata(),
        )

    def named(self, name: str) -> RegistrationBuilder:
        self._request.name = name
        return self

    def described(self, description: str) -> RegistrationBuilder:
        self._request.description = description
        return self

    def as_latest(self, value: bool = True) -> RegistrationBuilder:
        self._request.is_latest = value
        return self

    def of_type(self, dataset_type: DatasetType) -> RegistrationBuilder:
        self._request.dataset_type = dataset_type
        return self

    def with_location(
        self,
        location_uri: str,
        *,
        asset_type: AssetType,
        storage_platform: StoragePlatform | None = None,
        file_format: str | None = None,
        description: str | None = None,
        size_bytes: int | None = None,
        encoding: str | None = None,
        checksum: str | None = None,
        checksum_alg: str | None = None,
        file_count: int | None = None,
        includes_pattern: str | None = None,
        excludes_pattern: str | None = None,
    ) -> RegistrationBuilder:
        self._request.locations.append(
            DataAssetRequest(
                location_uri=location_uri,
                asset_type=asset_type,
                storage_platform=storage_platform,
                file_format=file_format,
                description=description,
                size_bytes=size_bytes,
                encoding=encoding,
                checksum=checksum,
                checksum_alg=checksum_alg,
                file_count=file_count,
                includes_pattern=includes_pattern,
                excludes_pattern=excludes_pattern,
            )
        )
        return self

    def with_governance(self, **kwargs: Any) -> RegistrationBuilder:
        self._request.governance = GovernanceMetadata(**kwargs)
        return self

    def with_sample(self, **kwargs: Any) -> RegistrationBuilder:
        # Create new sample metadata, completely replacing any existing sample metadata
        sample = SampleMetadata(**kwargs)

        # Preserve existing dataset-level custom metadata
        existing_dataset_data = self._request.metadata.model_dump()
        # Update with new sample while preserving other fields
        dataset_data = {
            **existing_dataset_data,
            "sample": sample,
        }
        self._request.metadata = DatasetMetadata(**dataset_data)
        return self

    def with_experiment(self, **kwargs: Any) -> RegistrationBuilder:
        # Create new experiment metadata, completely replacing any existing experiment metadata
        experiment = ExperimentMetadata(**kwargs)

        # Preserve existing dataset-level custom metadata
        existing_dataset_data = self._request.metadata.model_dump()
        # Update with new experiment while preserving other fields
        dataset_data = {
            **existing_dataset_data,
            "experiment": experiment,
        }
        self._request.metadata = DatasetMetadata(**dataset_data)
        return self

    def with_data_summary(self, **kwargs: Any) -> RegistrationBuilder:
        # Create new data_summary metadata, completely replacing any existing data_summary metadata
        data_summary = DataSummaryMetadata(**kwargs)

        # Preserve existing dataset-level custom metadata
        existing_dataset_data = self._request.metadata.model_dump()
        # Update with new data_summary while preserving other fields
        dataset_data = {
            **existing_dataset_data,
            "data_summary": data_summary,
        }
        self._request.metadata = DatasetMetadata(**dataset_data)
        return self

    def with_custom_metadata(self, **kwargs: Any) -> RegistrationBuilder:
        """Add custom key-value pairs to dataset-level metadata.

        For metadata that doesn't belong to sample, experiment, or data_summary categories.
        """
        # Get existing custom fields (extra fields beyond the model definition)
        existing_data = self._request.metadata.model_dump()
        # Merge existing data with new kwargs, with new kwargs taking precedence
        merged_data = {**existing_data, **kwargs}

        self._request.metadata = DatasetMetadata(**merged_data)
        return self

    def with_data_quality(self, **kwargs: Any) -> RegistrationBuilder:
        self._request.data_quality = DataQualityChecks(**kwargs)
        return self

    def with_lineage(
        self,
        source: str | DatasetRef,
        *,
        lineage_type: LineageType,
    ) -> RegistrationBuilder:
        if isinstance(source, str):
            self._request.lineage.append(
                LineageSpec(
                    lineage_type=lineage_type,
                    source_dataset_id=source,
                )
            )
        else:
            self._request.lineage.append(
                LineageSpec(
                    lineage_type=lineage_type,
                    source_ref=source,
                )
            )
        return self

    def build(self) -> RegistrationRequest:
        return self._request

    def submit(
        self,
        update_if_exists: bool = False,
        error_on_duplicate: bool = True,
    ) -> str:
        """Build the request and register it. Returns the new dataset_id."""
        if self._client is None:
            raise RuntimeError(
                "No client bound to this builder. "
                "Use client.new_registration(...) instead of RegistrationBuilder(...) directly."
            )
        return self._client.register(
            self.build(),
            update_if_exists=update_if_exists,
            error_on_duplicate=error_on_duplicate,
        )
