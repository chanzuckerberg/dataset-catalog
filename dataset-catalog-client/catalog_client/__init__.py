"""
catalog_client — Python client for the MetaHub Catalog API.

Quick start (sync):
    from catalog_client import CatalogClient, DatasetModality, AssetType, OntologyEntry

    with CatalogClient(base_url="https://catalog.example.com", api_token="...") as client:
        dataset_id = (
            client.new_registration(
                canonical_id="my-dataset",
                version="1.0.0",
                project="atlas",
                modality=DatasetModality.sequencing,
            )
            .with_location("s3://bucket/path", asset_type=AssetType.folder)
            .with_governance(data_owner="team-x", is_phi=False)
            .with_sample(organism=[OntologyEntry(label="Homo sapiens", ontology_id="NCBITaxon:9606")])
            .submit()
        )

Quick start (async):
    from catalog_client import AsyncCatalogClient

    async with AsyncCatalogClient(base_url="...", api_token="...") as client:
        dataset_id = await client.register(request)
"""
from catalog_client.client.catalog import AsyncCatalogClient, CatalogClient
from catalog_client.exceptions import (
    AuthenticationError,
    CatalogConnectionError,
    CatalogError,
    CatalogHTTPError,
    CatalogServerError,
    LineageResolutionError,
    NotFoundError,
    ValidationError,
)
from catalog_client.models import (
    AssetType,
    CollectionCreate,
    CollectionResponse,
    CollectionType,
    CollectionUpdate,
    DataAssetRequest,
    DataAssetResponse,
    DataQualityChecks,
    DatasetCreate,
    DatasetMetadata,
    DatasetModality,
    DatasetRef,
    DatasetResponse,
    DatasetType,
    DatasetUpdate,
    DatasetWithRelationsResponse,
    ExperimentMetadata,
    GovernanceMetadata,
    LineageEdgeCreate,
    LineageEdgeResponse,
    LineageType,
    OntologyEntry,
    PaginatedResponse,
    SampleMetadata,
    StoragePlatform,
    TissueEntry,
)
from catalog_client.registration import (
    LineageSpec,
    RegistrationBuilder,
    RegistrationRequest,
)

__all__ = [
    # Clients
    "AsyncCatalogClient",
    "CatalogClient",
    # Registration
    "LineageSpec",
    "RegistrationBuilder",
    "RegistrationRequest",
    # Models
    "AssetType",
    "CollectionCreate",
    "CollectionResponse",
    "CollectionType",
    "CollectionUpdate",
    "DataAssetRequest",
    "DataAssetResponse",
    "DataQualityChecks",
    "DatasetCreate",
    "DatasetMetadata",
    "DatasetModality",
    "DatasetRef",
    "DatasetResponse",
    "DatasetType",
    "DatasetUpdate",
    "DatasetWithRelationsResponse",
    "ExperimentMetadata",
    "GovernanceMetadata",
    "LineageEdgeCreate",
    "LineageEdgeResponse",
    "LineageType",
    "OntologyEntry",
    "PaginatedResponse",
    "SampleMetadata",
    "StoragePlatform",
    "TissueEntry",
    # Exceptions
    "AuthenticationError",
    "CatalogConnectionError",
    "CatalogError",
    "CatalogHTTPError",
    "CatalogServerError",
    "LineageResolutionError",
    "NotFoundError",
    "ValidationError",
]
