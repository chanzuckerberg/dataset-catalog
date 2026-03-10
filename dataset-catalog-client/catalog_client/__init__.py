from catalog_client._context import get_client
from catalog_client.client import CatalogClient, CollectionClient, DatasetClient, LineageClient, TokenClient
from catalog_client.exceptions import AuthenticationError, CatalogError, CatalogServerError, NotFoundError
from catalog_client.models import (
    APITokenCreatedResponse,
    APITokenResponse,
    AssetType,
    CollectionCreate,
    CollectionResponse,
    CollectionUpdate,
    DataAssetRequest,
    DataAssetResponse,
    DataSummaryMetadata,
    DatasetCreate,
    DatasetMetadata,
    DatasetModality,
    DatasetResponse,
    DatasetType,
    DatasetUpdate,
    ExperimentMetadata,
    GovernanceMetadata,
    LineageEdgeCreate,
    LineageEdgeResponse,
    LineageType,
    OntologyEntry,
    PaginatedResponse,
    SampleMetadata,
    TissueEntry,
    TokenExpiry,
    TokenIssueRequest,
    TokenUserResponse,
    TokenValidateRequest,
    TokenValidateResponse,
)

__all__ = [
    # Clients
    "CatalogClient",
    "CollectionClient",
    "DatasetClient",
    "LineageClient",
    "TokenClient",
    # Exceptions
    "CatalogError",
    "AuthenticationError",
    "NotFoundError",
    "CatalogServerError",
    # Enums
    "AssetType",
    "DatasetModality",
    "DatasetType",
    "LineageType",
    "TokenExpiry",
    # Asset models
    "DataAssetRequest",
    "DataAssetResponse",
    # Dataset models
    "DatasetCreate",
    "DatasetUpdate",
    "DatasetResponse",
    # Metadata models
    "DatasetMetadata",
    "GovernanceMetadata",
    "ExperimentMetadata",
    "SampleMetadata",
    "DataSummaryMetadata",
    "OntologyEntry",
    "TissueEntry",
    # Collection models
    "CollectionCreate",
    "CollectionUpdate",
    "CollectionResponse",
    # Lineage models
    "LineageEdgeCreate",
    "LineageEdgeResponse",
    # Pagination
    "PaginatedResponse",
    # Token models
    "TokenIssueRequest",
    "TokenValidateRequest",
    "TokenValidateResponse",
    "APITokenResponse",
    "APITokenCreatedResponse",
    "TokenUserResponse",
    # Utilities
    "get_client",
]
