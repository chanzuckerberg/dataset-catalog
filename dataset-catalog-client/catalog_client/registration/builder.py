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
            metadata=DatasetMetadata(
                sample=None,
                experiment=None,
                data_summary=None,
            ),
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
        sample = SampleMetadata(**kwargs)
        self._request.metadata = DatasetMetadata(
            sample=sample,
            experiment=self._request.metadata.experiment,
            data_summary=self._request.metadata.data_summary,
        )
        return self

    def with_experiment(self, **kwargs: Any) -> RegistrationBuilder:
        experiment = ExperimentMetadata(**kwargs)
        self._request.metadata = DatasetMetadata(
            sample=self._request.metadata.sample,
            experiment=experiment,
            data_summary=self._request.metadata.data_summary,
        )
        return self

    def with_data_summary(self, **kwargs: Any) -> RegistrationBuilder:
        data_summary = DataSummaryMetadata(**kwargs)
        self._request.metadata = DatasetMetadata(
            sample=self._request.metadata.sample,
            experiment=self._request.metadata.experiment,
            data_summary=data_summary,
        )
        return self

    def with_data_quality(self, **kwargs: Any) -> RegistrationBuilder:
        self._request.data_quality = DataQualityChecks(**kwargs)
        return self

    def derived_from(
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

    def submit(self) -> str:
        """Build the request and register it. Returns the new dataset_id."""
        if self._client is None:
            raise RuntimeError(
                "No client bound to this builder. "
                "Use client.new_registration(...) instead of RegistrationBuilder(...) directly."
            )
        return self._client.register(self.build())
