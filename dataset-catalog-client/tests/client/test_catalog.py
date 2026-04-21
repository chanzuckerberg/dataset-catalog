import pytest
from pytest_httpx import HTTPXMock

from catalog_client.client.catalog import AsyncCatalogClient, CatalogClient
from catalog_client.exceptions import (
    DuplicateDatasetError,
    LineageResolutionError,
    CatalogError,
)
from catalog_client.models.asset import AssetType, DataAssetRequest
from catalog_client.models.dataset import DatasetModality, DatasetRef
from catalog_client.models.governance import GovernanceMetadata
from catalog_client.models.lineage import LineageType
from catalog_client.models.metadata import DatasetMetadata
from catalog_client.registration.builder import RegistrationBuilder
from catalog_client.registration.request import LineageSpec, RegistrationRequest

BASE = "http://test.local"
TOKEN = "test-token"

DATASET_RESPONSE = {
    "id": "new-uuid",
    "tombstoned": False,
    "created_at": "2024-01-01T00:00:00Z",
    "created_by": "user-1",
    "last_modified_at": "2024-01-01T00:00:00Z",
    "modified_by": None,
    "canonical_id": "ds-001",
    "version": "1.0.0",
    "project": "atlas",
    "locations": [],
    "name": "Test",
    "modality": "sequencing",
    "dataset_type": "raw",
    "governance": {},
    "data_quality": None,
    "metadata": {},
    "record_version": 1,
    "description": None,
    "doi": None,
    "cross_db_references": None,
    "is_latest": False,
    "record_schema_version": None,
    "metadata_schema": None,
}

EDGE_RESPONSE = {
    "id": "edge-1",
    "tombstoned": False,
    "created_at": "2024-01-01T00:00:00Z",
    "created_by": "user-1",
    "last_modified_at": "2024-01-01T00:00:00Z",
    "modified_by": None,
    "source_dataset_id": "parent-uuid",
    "destination_dataset_id": "new-uuid",
    "lineage_type": "transformed_from",
    "source_data_asset_id": None,
    "destination_data_asset_id": None,
    "lineage_metadata": None,
}

PARENT_PAGINATED = {
    "total": 1,
    "limit": 1000,
    "offset": 0,
    "results": [{**DATASET_RESPONSE, "id": "parent-uuid", "canonical_id": "parent-ds"}],
}


def _minimal_request(lineage=None) -> RegistrationRequest:
    return RegistrationRequest(
        canonical_id="ds-001",
        name="My Dataset",
        version="1.0.0",
        project="atlas",
        modality=DatasetModality.sequencing,
        locations=[
            DataAssetRequest(location_uri="s3://bucket/key", asset_type=AssetType.file)
        ],
        governance=GovernanceMetadata(),
        metadata=DatasetMetadata(),
        lineage=lineage or [],
    )


# --- CatalogClient ---


def test_catalog_client_has_sub_clients():
    client = CatalogClient(base_url=BASE, api_token=TOKEN)
    assert hasattr(client, "datasets")
    assert hasattr(client, "lineages")
    assert hasattr(client, "collections")
    client.close()


def test_catalog_client_context_manager(httpx_mock: HTTPXMock):
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        assert client is not None


def test_register_no_lineage(httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", json=EMPTY_PAGINATED)  # No existing datasets
    httpx_mock.add_response(method="POST", json=DATASET_RESPONSE, status_code=201)
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        dataset_id = client.register(_minimal_request())
    assert dataset_id == "new-uuid"


def test_register_with_lineage_by_uuid(httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", json=EMPTY_PAGINATED)  # No existing datasets
    httpx_mock.add_response(method="POST", json=DATASET_RESPONSE, status_code=201)
    httpx_mock.add_response(method="POST", json=EDGE_RESPONSE, status_code=201)
    req = _minimal_request(
        lineage=[
            LineageSpec(
                lineage_type=LineageType.transformed_from,
                source_dataset_id="parent-uuid",
            )
        ]
    )
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        dataset_id = client.register(req)
    assert dataset_id == "new-uuid"


def test_register_with_lineage_by_ref(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET", json=EMPTY_PAGINATED
    )  # No existing datasets (for create_or_update check)
    httpx_mock.add_response(method="POST", json=DATASET_RESPONSE, status_code=201)
    httpx_mock.add_response(
        method="GET", json=PARENT_PAGINATED
    )  # For lineage resolution
    httpx_mock.add_response(method="POST", json=EDGE_RESPONSE, status_code=201)
    ref = DatasetRef("parent-ds", "1.0.0", "atlas")
    req = _minimal_request(
        lineage=[LineageSpec(lineage_type=LineageType.transformed_from, source_ref=ref)]
    )
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        dataset_id = client.register(req)
    assert dataset_id == "new-uuid"


def test_register_ref_not_found_raises(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET", json=EMPTY_PAGINATED
    )  # No existing datasets (for create_or_update check)
    httpx_mock.add_response(method="POST", json=DATASET_RESPONSE, status_code=201)
    httpx_mock.add_response(
        method="GET",
        json={
            "total": 0,
            "limit": 1000,
            "offset": 0,
            "results": [],
        },  # For lineage resolution - not found
    )
    ref = DatasetRef("missing-ds", "1.0.0", "atlas")
    req = _minimal_request(
        lineage=[LineageSpec(lineage_type=LineageType.transformed_from, source_ref=ref)]
    )
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        with pytest.raises(LineageResolutionError) as exc_info:
            client.register(req)
    assert exc_info.value.ref == ref


def test_new_registration_returns_builder():
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        builder = client.new_registration(
            canonical_id="ds-001",
            name="Test Dataset",
            version="1.0.0",
            project="atlas",
            modality=DatasetModality.sequencing,
        )
    assert isinstance(builder, RegistrationBuilder)


# --- create_or_update tests ---

EXISTING_DATASET_RESPONSE = {
    **DATASET_RESPONSE,
    "id": "existing-uuid",
    "canonical_id": "ds-001",  # Same as in _minimal_request
}

EXISTING_PAGINATED = {
    "total": 1,
    "limit": 10,
    "offset": 0,
    "results": [EXISTING_DATASET_RESPONSE],
}

MULTIPLE_EXISTING_PAGINATED = {
    "total": 2,
    "limit": 10,
    "offset": 0,
    "results": [
        EXISTING_DATASET_RESPONSE,
        {**EXISTING_DATASET_RESPONSE, "id": "existing-uuid-2"},
    ],
}

EMPTY_PAGINATED = {
    "total": 0,
    "limit": 10,
    "offset": 0,
    "results": [],
}


def test_register_default_behavior_new_dataset_creates(httpx_mock: HTTPXMock):
    """Default behavior: new dataset should be created"""
    httpx_mock.add_response(method="GET", json=EMPTY_PAGINATED)  # No existing datasets
    httpx_mock.add_response(method="POST", json=DATASET_RESPONSE, status_code=201)

    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        dataset_id = client.register(_minimal_request())

    assert dataset_id == "new-uuid"


def test_register_default_behavior_duplicate_raises_error(httpx_mock: HTTPXMock):
    """Default behavior: duplicate dataset should raise DuplicateDatasetError"""
    httpx_mock.add_response(
        method="GET", json=EXISTING_PAGINATED
    )  # Found existing dataset

    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        with pytest.raises(DuplicateDatasetError) as exc_info:
            client.register(_minimal_request())

    assert "ds-001" in str(exc_info.value)
    assert "update_if_exists=True" in str(exc_info.value)
    assert exc_info.value.ref.canonical_id == "ds-001"
    assert exc_info.value.ref.version == "1.0.0"
    assert exc_info.value.ref.project == "atlas"


def test_register_update_if_exists_new_dataset_creates(httpx_mock: HTTPXMock):
    """update_if_exists=True: new dataset should be created"""
    httpx_mock.add_response(method="GET", json=EMPTY_PAGINATED)  # No existing datasets
    httpx_mock.add_response(method="POST", json=DATASET_RESPONSE, status_code=201)

    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        dataset_id = client.register(
            _minimal_request(), update_if_exists=True, error_on_duplicate=False
        )

    assert dataset_id == "new-uuid"


def test_register_update_if_exists_existing_dataset_updates(httpx_mock: HTTPXMock):
    """update_if_exists=True: existing dataset should be updated"""
    httpx_mock.add_response(
        method="GET", json=EXISTING_PAGINATED
    )  # Found existing dataset
    httpx_mock.add_response(
        method="PATCH", json=EXISTING_DATASET_RESPONSE, status_code=200
    )  # Update response

    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        dataset_id = client.register(
            _minimal_request(), update_if_exists=True, error_on_duplicate=False
        )

    assert dataset_id == "existing-uuid"  # Should return existing dataset ID


def test_register_skip_on_duplicate_new_dataset_creates(httpx_mock: HTTPXMock):
    """error_on_duplicate=False, update_if_exists=False: new dataset should be created"""
    httpx_mock.add_response(method="GET", json=EMPTY_PAGINATED)  # No existing datasets
    httpx_mock.add_response(method="POST", json=DATASET_RESPONSE, status_code=201)

    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        dataset_id = client.register(_minimal_request(), error_on_duplicate=False)

    assert dataset_id == "new-uuid"


def test_register_skip_on_duplicate_existing_dataset_returns_id(httpx_mock: HTTPXMock):
    """error_on_duplicate=False, update_if_exists=False: existing dataset should return existing ID"""
    httpx_mock.add_response(
        method="GET", json=EXISTING_PAGINATED
    )  # Found existing dataset

    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        dataset_id = client.register(_minimal_request(), error_on_duplicate=False)

    assert dataset_id == "existing-uuid"  # Should return existing dataset ID


def test_register_invalid_parameter_combination_raises_error(httpx_mock: HTTPXMock):
    """Both update_if_exists=True and error_on_duplicate=True should raise ValueError"""
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        with pytest.raises(ValueError) as exc_info:
            client.register(
                _minimal_request(), update_if_exists=True, error_on_duplicate=True
            )

    assert "cannot both be True" in str(exc_info.value)


def test_register_multiple_existing_datasets_raises_error(httpx_mock: HTTPXMock):
    """Multiple existing datasets with same ref should raise CatalogError"""
    httpx_mock.add_response(
        method="GET", json=MULTIPLE_EXISTING_PAGINATED
    )  # Multiple existing datasets

    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        with pytest.raises(CatalogError) as exc_info:
            client.register(_minimal_request(), error_on_duplicate=False)

    assert "Multiple datasets found (2)" in str(exc_info.value)


def test_register_with_lineage_update_if_exists(httpx_mock: HTTPXMock):
    """Test that lineage is still created when update_if_exists=True"""
    httpx_mock.add_response(
        method="GET", json=EXISTING_PAGINATED
    )  # Found existing dataset
    httpx_mock.add_response(
        method="PATCH", json=EXISTING_DATASET_RESPONSE, status_code=200
    )  # Update response
    httpx_mock.add_response(
        method="POST", json=EDGE_RESPONSE, status_code=201
    )  # Lineage creation

    req = _minimal_request(
        lineage=[
            LineageSpec(
                lineage_type=LineageType.transformed_from,
                source_dataset_id="parent-uuid",
            )
        ]
    )

    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        dataset_id = client.register(
            req, update_if_exists=True, error_on_duplicate=False
        )

    assert dataset_id == "existing-uuid"


def test_register_with_lineage_error_on_duplicate(httpx_mock: HTTPXMock):
    """Test that DuplicateDatasetError is raised before lineage processing"""
    httpx_mock.add_response(
        method="GET", json=EXISTING_PAGINATED
    )  # Found existing dataset
    # No lineage creation call should be made

    req = _minimal_request(
        lineage=[
            LineageSpec(
                lineage_type=LineageType.transformed_from,
                source_dataset_id="parent-uuid",
            )
        ]
    )

    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        with pytest.raises(DuplicateDatasetError):
            client.register(req)  # Using default error_on_duplicate=True


# --- AsyncCatalogClient ---


async def test_async_catalog_client_has_sub_clients():
    async with AsyncCatalogClient(base_url=BASE, api_token=TOKEN) as client:
        assert hasattr(client, "datasets")
        assert hasattr(client, "lineages")
        assert hasattr(client, "collections")


async def test_async_register_no_lineage(httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="POST", json=DATASET_RESPONSE, status_code=201)
    async with AsyncCatalogClient(base_url=BASE, api_token=TOKEN) as client:
        dataset_id = await client.register(_minimal_request())
    assert dataset_id == "new-uuid"
