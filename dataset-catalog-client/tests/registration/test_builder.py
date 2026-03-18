from unittest.mock import MagicMock

from catalog_client.models.asset import AssetType
from catalog_client.models.dataset import DatasetModality, DatasetRef
from catalog_client.models.lineage import LineageType
from catalog_client.models.metadata import OntologyEntry
from catalog_client.registration.builder import RegistrationBuilder
from catalog_client.registration.request import RegistrationRequest


def _builder(**kwargs):
    defaults = dict(
        canonical_id="ds-001",
        version="1.0.0",
        project="atlas",
        modality=DatasetModality.sequencing,
    )
    defaults.update(kwargs)
    return RegistrationBuilder(**defaults)


def test_builder_build_returns_registration_request():
    req = (
        _builder()
        .with_location("s3://bucket/key", asset_type=AssetType.file)
        .with_governance(data_owner="team-x", is_phi=False)
        .with_sample(
            organism=[OntologyEntry(label="Homo sapiens", ontology_id="NCBITaxon:9606")]
        )
        .with_experiment(assay=["10x Chromium"], assay_ontology_id=["EFO:0009922"])
        .build()
    )
    assert isinstance(req, RegistrationRequest)
    assert req.canonical_id == "ds-001"
    assert req.version == "1.0.0"
    assert req.project == "atlas"
    assert len(req.locations) == 1
    assert req.locations[0].location_uri == "s3://bucket/key"
    assert req.governance.data_owner == "team-x"
    assert req.metadata.sample.organism[0].label == "Homo sapiens"
    assert req.metadata.experiment.assay == ["10x Chromium"]


def test_builder_multiple_locations():
    req = (
        _builder()
        .with_location("s3://bucket/a", asset_type=AssetType.file)
        .with_location("s3://bucket/b", asset_type=AssetType.folder)
        .build()
    )
    assert len(req.locations) == 2


def test_builder_derived_from_uuid():
    req = (
        _builder()
        .with_location("s3://x", asset_type=AssetType.file)
        .derived_from("uuid-parent", lineage_type=LineageType.transformed_from)
        .build()
    )
    assert len(req.lineage) == 1
    assert req.lineage[0].source_dataset_id == "uuid-parent"
    assert req.lineage[0].source_ref is None


def test_builder_derived_from_ref():
    ref = DatasetRef("parent", "1.0.0", "atlas")
    req = (
        _builder()
        .with_location("s3://x", asset_type=AssetType.file)
        .derived_from(ref, lineage_type=LineageType.version_of)
        .build()
    )
    assert req.lineage[0].source_ref == ref
    assert req.lineage[0].source_dataset_id is None


def test_builder_submit_calls_client_register():
    mock_client = MagicMock()
    mock_client.register.return_value = "new-dataset-id"
    builder = _builder().with_location("s3://x", asset_type=AssetType.file)
    builder._client = mock_client

    result = builder.submit()

    mock_client.register.assert_called_once()
    assert result == "new-dataset-id"


def test_builder_is_latest_defaults_false():
    req = _builder().with_location("s3://x", asset_type=AssetType.file).build()
    assert req.is_latest is False
