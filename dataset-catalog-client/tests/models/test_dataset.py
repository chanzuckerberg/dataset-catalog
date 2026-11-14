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
    AuditLogEventType,
    DatasetAuditLogResponse,
    DatasetModality,
    DatasetRef,
    DatasetRequest,
    DatasetResponse,
    DatasetType,
    RecordStatus,
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
        governance=GovernanceMetadata(
            data_steward="team-data", is_pii=False, is_phi=False
        ),
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
            governance=GovernanceMetadata(
                data_steward="team-data", is_pii=False, is_phi=False
            ),
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
    assert asset.instance_id is None and asset.relative_path is None


def test_dataset_create_project_required():
    """project is a signature field and must be provided (schema v1.4.0)."""
    with pytest.raises(ValidationError):
        DatasetRequest(
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
            governance=GovernanceMetadata(
                data_steward="team-data", is_pii=False, is_phi=False
            ),
            metadata=DatasetMetadata(),
        )


def test_dataset_create_is_latest_defaults_false():
    ds = _minimal_create()
    assert ds.is_latest is True


def test_dataset_defaults_to_current_schema_version():
    assert _minimal_create().record_schema_version == "v1.8.0"


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
        "governance": {"data_steward": "team-data", "is_pii": False, "is_phi": False},
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
    assert ds.record_status is None

    ds = DatasetResponse.model_validate({**data, "record_status": "active"})
    assert ds.record_status is RecordStatus.active


def test_dataset_response_tolerates_missing_data_steward():
    """A record written before schema v1.5.0 made `data_steward` required still parses
    end to end, not just at the governance model."""
    data = {
        "id": "uuid-1",
        "tombstoned": False,
        "created_at": "2024-01-01T00:00:00Z",
        "last_modified_at": "2024-01-01T00:00:00Z",
        "canonical_id": "ds-001",
        "version": "1.0.0",
        "project": "atlas",
        "locations": [],
        "name": "Test",
        "modality": "sequencing",
        "governance": {"is_pii": False, "is_phi": False},
        "metadata": {},
        "record_version": 1,
        "record_schema_version": "v1.4.0",
    }
    ds = DatasetResponse.model_validate(data)
    assert ds.governance.data_steward is None


def test_dataset_type_accepts_analysis():
    """Added in v1.7.0, alongside raw and processed."""
    assert DatasetType("analysis") is DatasetType.analysis


def test_audit_log_carries_resolved_actor_identity():
    """actor is the token id; the actor_* fields name the human behind it."""
    entry = DatasetAuditLogResponse(
        id="audit-1",
        dataset_id="ds-1",
        event_type=AuditLogEventType.created,
        actor="tok-1",
        actor_name="A Person",
        actor_email="person@example.com",
        actor_team="data",
        timestamp="2024-01-01T00:00:00Z",
        db_created_at="2024-01-01T00:00:00Z",
        snapshot={},
    )
    assert entry.actor_email == "person@example.com"
    assert entry.actor_team == "data"


def test_root_uri_is_optional_and_omitted_when_unset():
    """Added in v1.8.0: the server derives the root when the writer leaves it out."""
    assert "root_uri" not in _minimal_create().model_dump(exclude_unset=True)


def test_root_uri_rejects_empty_string():
    with pytest.raises(ValidationError):
        _minimal_create(root_uri="")


def test_data_asset_response_carries_instance_fields():
    asset = DataAssetResponse.model_validate(
        {
            "id": "asset-1",
            "tombstoned": False,
            "created_at": "2024-01-01T00:00:00Z",
            "last_modified_at": "2024-01-01T00:00:00Z",
            "dataset_id": "uuid-1",
            "location_uri": "s3://bucket/run42/cells.parquet",
            "asset_type": "file",
            "storage_platform": "s3",
            "instance_id": "inst-1",
            "relative_path": "cells.parquet",
        }
    )
    assert asset.instance_id == "inst-1"
    assert asset.relative_path == "cells.parquet"
