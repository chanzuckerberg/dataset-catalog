import pytest
from pytest_httpx import HTTPXMock

from catalog_client.client.catalog import AsyncCatalogClient, CatalogClient
from catalog_client.exceptions import LineageResolutionError
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
    "dataset_metadata": {},
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
    "total": 1, "limit": 1000, "offset": 0,
    "results": [{**DATASET_RESPONSE, "id": "parent-uuid", "canonical_id": "parent-ds"}],
}


def _minimal_request(lineage=None) -> RegistrationRequest:
    return RegistrationRequest(
        canonical_id="ds-001",
        name="My Dataset",
        version="1.0.0",
        project="atlas",
        modality=DatasetModality.sequencing,
        locations=[DataAssetRequest(location_uri="s3://bucket/key", asset_type=AssetType.file)],
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
    httpx_mock.add_response(method="POST", json=DATASET_RESPONSE, status_code=201)
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        dataset_id = client.register(_minimal_request())
    assert dataset_id == "new-uuid"


def test_register_with_lineage_by_uuid(httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="POST", json=DATASET_RESPONSE, status_code=201)
    httpx_mock.add_response(method="POST", json=EDGE_RESPONSE, status_code=201)
    req = _minimal_request(lineage=[
        LineageSpec(lineage_type=LineageType.transformed_from, source_dataset_id="parent-uuid")
    ])
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        dataset_id = client.register(req)
    assert dataset_id == "new-uuid"


def test_register_with_lineage_by_ref(httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="POST", json=DATASET_RESPONSE, status_code=201)
    httpx_mock.add_response(method="GET", json=PARENT_PAGINATED)
    httpx_mock.add_response(method="POST", json=EDGE_RESPONSE, status_code=201)
    ref = DatasetRef("parent-ds", "1.0.0", "atlas")
    req = _minimal_request(lineage=[
        LineageSpec(lineage_type=LineageType.transformed_from, source_ref=ref)
    ])
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        dataset_id = client.register(req)
    assert dataset_id == "new-uuid"


def test_register_ref_not_found_raises(httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="POST", json=DATASET_RESPONSE, status_code=201)
    httpx_mock.add_response(method="GET", json={"total": 0, "limit": 1000, "offset": 0, "results": []})
    ref = DatasetRef("missing-ds", "1.0.0", "atlas")
    req = _minimal_request(lineage=[
        LineageSpec(lineage_type=LineageType.transformed_from, source_ref=ref)
    ])
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        with pytest.raises(LineageResolutionError) as exc_info:
            client.register(req)
    assert exc_info.value.ref == ref


def test_new_registration_returns_builder():
    with CatalogClient(base_url=BASE, api_token=TOKEN) as client:
        builder = client.new_registration(
            canonical_id="ds-001",
            version="1.0.0",
            project="atlas",
            modality=DatasetModality.sequencing,
        )
    assert isinstance(builder, RegistrationBuilder)


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
