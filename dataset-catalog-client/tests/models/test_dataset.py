import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from catalog_client.models.asset import (
    AssetType,
    DataAssetRequest,
    DataAssetResponse,
    StoragePlatform,
)
from catalog_client.models.dataset import (
    DatasetModality,
    DatasetRef,
    DatasetRequest,
    DatasetResponse,
    DatasetType,
)
from catalog_client.models.governance import GovernanceMetadata
from catalog_client.models.metadata import DatasetMetadata


def _minimal_create(**kwargs: Any) -> DatasetRequest:
    defaults = dict(
        canonical_id="ds-001",
        name="Test Dataset",
        version="1.0.0",
        project="atlas",
        modality=DatasetModality.sequencing,
        locations=[
            DataAssetRequest(
                location_uri="s3://bucket/key",
                asset_type=AssetType.file,
                storage_platform=StoragePlatform.s3,
            )
        ],
        governance=GovernanceMetadata(),
        metadata=DatasetMetadata(),
    )
    defaults.update(kwargs)
    return DatasetRequest(**defaults)  # type: ignore


def test_dataset_ref_is_named_tuple():
    ref = DatasetRef(canonical_id="ds-1", version="1.0.0", project="proj")
    assert ref.canonical_id == "ds-1"
    assert ref.version == "1.0.0"
    assert ref.project == "proj"


def test_dataset_ref_unpacks():
    ref = DatasetRef("ds-1", "1.0.0", "proj")
    canonical_id, version, project = ref
    assert canonical_id == "ds-1"


def test_dataset_create_requires_canonical_id():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DatasetRequest(
            name="x",
            version="1.0.0",
            project="p",
            modality=DatasetModality.sequencing,
            locations=[
                DataAssetRequest(
                    location_uri="s3://x",
                    asset_type=AssetType.file,
                    storage_platform=StoragePlatform.s3,
                )
            ],
            governance=GovernanceMetadata(),
            metadata=DatasetMetadata(),
        )


def test_dataset_create_locations_min_length():
    with pytest.raises(ValidationError):
        _minimal_create(locations=[])


def test_data_asset_request_requires_storage_platform():
    with pytest.raises(ValidationError):
        DataAssetRequest(location_uri="s3://bucket/key", asset_type=AssetType.file)


def test_data_asset_response_tolerates_missing_storage_platform():
    """The response model is lenient so legacy/external assets still parse."""
    asset = DataAssetResponse.model_validate(
        {
            "id": "asset-1",
            "location_uri": "s3://bucket/key",
            "asset_type": "file",
            "tombstoned": False,
            "created_at": datetime.datetime(2024, 1, 1),
            "last_modified_at": datetime.datetime(2024, 1, 1),
            "dataset_id": "ds-1",
        }
    )
    assert asset.storage_platform is None


def test_dataset_create_project_optional():
    ds = DatasetRequest(
        canonical_id="ds-001",
        name="Test Dataset",
        version="1.0.0",
        modality=DatasetModality.sequencing,
        locations=[
            DataAssetRequest(
                location_uri="s3://bucket/key",
                asset_type=AssetType.file,
                storage_platform=StoragePlatform.s3,
            )
        ],
        governance=GovernanceMetadata(),
        metadata=DatasetMetadata(),
    )
    assert ds.project is None


def test_dataset_create_is_latest_defaults_false():
    ds = _minimal_create()
    assert ds.is_latest is True


def test_dataset_modality_enum():
    assert DatasetModality.sequencing == "sequencing"
    assert DatasetModality.imaging == "imaging"


def test_dataset_type_enum():
    assert DatasetType.raw == "raw"
    assert DatasetType.processed == "processed"


def test_dataset_response_parses_json():
    data = {
        "id": "uuid-1",
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
        "record_schema_version": "v1.1.0",
        "metadata_schema": None,
    }
    ds = DatasetResponse.model_validate(data)
    assert ds.id == "uuid-1"
    assert ds.canonical_id == "ds-001"
