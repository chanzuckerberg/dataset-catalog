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
        version: str,
        project: str,
        modality: DatasetModality,
        *,
        client: CatalogClient | None = None,
    ) -> None:
        self._canonical_id = canonical_id
        self._version = version
        self._project = project
        self._modality = modality
        self._client = client

        self._name: str | None = None
        self._description: str | None = None
        self._dataset_type: DatasetType | None = None
        self._is_latest: bool = True
        self._locations: list[DataAssetRequest] = []
        self._governance: GovernanceMetadata = GovernanceMetadata()
        self._sample: SampleMetadata = SampleMetadata()
        self._experiment: ExperimentMetadata = ExperimentMetadata()
        self._data_summary: DataSummaryMetadata = DataSummaryMetadata()
        self._data_quality: DataQualityChecks | None = None
        self._lineage: list[LineageSpec] = []

    def named(self, name: str) -> RegistrationBuilder:
        self._name = name
        return self

    def described(self, description: str) -> RegistrationBuilder:
        self._description = description
        return self

    def as_latest(self, value: bool = True) -> RegistrationBuilder:
        self._is_latest = value
        return self

    def of_type(self, dataset_type: DatasetType) -> RegistrationBuilder:
        self._dataset_type = dataset_type
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
        self._locations.append(
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
        self._governance = GovernanceMetadata(**kwargs)
        return self

    def with_sample(self, **kwargs: Any) -> RegistrationBuilder:
        self._sample = SampleMetadata(**kwargs)
        return self

    def with_experiment(self, **kwargs: Any) -> RegistrationBuilder:
        self._experiment = ExperimentMetadata(**kwargs)
        return self

    def with_data_summary(self, **kwargs: Any) -> RegistrationBuilder:
        self._data_summary = DataSummaryMetadata(**kwargs)
        return self

    def with_data_quality(self, **kwargs: Any) -> RegistrationBuilder:
        self._data_quality = DataQualityChecks(**kwargs)
        return self

    def derived_from(
        self,
        source: str | DatasetRef,
        *,
        lineage_type: LineageType,
    ) -> RegistrationBuilder:
        if isinstance(source, str):
            self._lineage.append(
                LineageSpec(
                    lineage_type=lineage_type,
                    source_dataset_id=source,
                )
            )
        else:
            self._lineage.append(
                LineageSpec(
                    lineage_type=lineage_type,
                    source_ref=source,
                )
            )
        return self

    def build(self) -> RegistrationRequest:
        name = self._name or self._canonical_id
        return RegistrationRequest(
            canonical_id=self._canonical_id,
            name=name,
            version=self._version,
            project=self._project,
            modality=self._modality,
            locations=self._locations,
            governance=self._governance,
            metadata=DatasetMetadata(
                sample=self._sample,
                experiment=self._experiment,
                data_summary=self._data_summary,
            ),
            description=self._description,
            dataset_type=self._dataset_type,
            data_quality=self._data_quality,
            is_latest=self._is_latest,
            lineage=self._lineage,
        )

    def submit(self) -> str:
        """Build the request and register it. Returns the new dataset_id."""
        if self._client is None:
            raise RuntimeError(
                "No client bound to this builder. "
                "Use client.new_registration(...) instead of RegistrationBuilder(...) directly."
            )
        return self._client.register(self.build())
