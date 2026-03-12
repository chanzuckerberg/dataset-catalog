import pytest

from catalog_client.models.asset import AssetType, DataAssetRequest
from catalog_client.models.dataset import DatasetModality, DatasetRef
from catalog_client.models.governance import GovernanceMetadata
from catalog_client.models.lineage import LineageType
from catalog_client.models.metadata import DatasetMetadata
from catalog_client.registration.request import LineageSpec, RegistrationRequest


def _minimal_request(**kwargs) -> RegistrationRequest:
    defaults = dict(
        canonical_id="ds-001",
        name="My Dataset",
        version="1.0.0",
        project="atlas",
        modality=DatasetModality.sequencing,
        locations=[DataAssetRequest(location_uri="s3://bucket/key", asset_type=AssetType.file)],
        governance=GovernanceMetadata(),
        metadata=DatasetMetadata(),
    )
    defaults.update(kwargs)
    return RegistrationRequest(**defaults)


def test_registration_request_required_fields():
    r = _minimal_request()
    assert r.canonical_id == "ds-001"
    assert r.version == "1.0.0"
    assert r.project == "atlas"
    assert r.is_latest is False
    assert r.lineage == []


def test_registration_request_missing_canonical_id_raises():
    with pytest.raises(TypeError):
        RegistrationRequest(
            name="x",
            version="1.0.0",
            project="p",
            modality=DatasetModality.sequencing,
            locations=[DataAssetRequest(location_uri="s3://x", asset_type=AssetType.file)],
            governance=GovernanceMetadata(),
            metadata=DatasetMetadata(),
        )


def test_lineage_spec_by_uuid():
    spec = LineageSpec(
        lineage_type=LineageType.transformed_from,
        source_dataset_id="uuid-abc",
    )
    assert spec.source_dataset_id == "uuid-abc"
    assert spec.source_ref is None


def test_lineage_spec_by_ref():
    ref = DatasetRef(canonical_id="parent", version="1.0.0", project="proj")
    spec = LineageSpec(lineage_type=LineageType.version_of, source_ref=ref)
    assert spec.source_ref == ref
    assert spec.source_dataset_id is None


def test_lineage_spec_no_source_is_valid():
    # Option C: no lineage
    spec = LineageSpec(lineage_type=LineageType.copy_of)
    assert spec.source_dataset_id is None
    assert spec.source_ref is None


def test_registration_request_with_lineage():
    ref = DatasetRef("parent", "1.0.0", "atlas")
    r = _minimal_request(
        lineage=[LineageSpec(lineage_type=LineageType.transformed_from, source_ref=ref)]
    )
    assert len(r.lineage) == 1
    assert r.lineage[0].source_ref == ref
