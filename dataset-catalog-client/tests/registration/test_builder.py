from unittest.mock import MagicMock

from catalog_client.models.asset import AssetType
from catalog_client.models.dataset import DatasetModality, DatasetRef
from catalog_client.models.lineage import LineageType
from catalog_client.models.metadata import OntologyEntry, TissueEntry
from catalog_client.registration.builder import RegistrationBuilder
from catalog_client.registration.request import RegistrationRequest


def _builder(**kwargs):
    defaults = dict(
        canonical_id="ds-001",
        name="Test Dataset",
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
        .with_experiment(assay=[OntologyEntry(label="10x Chromium", ontology_id="EFO:0009922")])
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
    assert req.metadata.experiment.assay[0].label == "10x Chromium"
    assert req.metadata.experiment.assay[0].ontology_id == "EFO:0009922"


def test_builder_multiple_locations():
    req = (
        _builder()
        .with_location("s3://bucket/a", asset_type=AssetType.file)
        .with_location("s3://bucket/b", asset_type=AssetType.folder)
        .build()
    )
    assert len(req.locations) == 2


def test_builder_with_lineage_uuid():
    req = (
        _builder()
        .with_location("s3://x", asset_type=AssetType.file)
        .with_lineage("uuid-parent", lineage_type=LineageType.transformed_from)
        .build()
    )
    assert len(req.lineage) == 1
    assert req.lineage[0].source_dataset_id == "uuid-parent"
    assert req.lineage[0].source_ref is None


def test_builder_with_lineage_ref():
    ref = DatasetRef("parent", "1.0.0", "atlas")
    req = (
        _builder()
        .with_location("s3://x", asset_type=AssetType.file)
        .with_lineage(ref, lineage_type=LineageType.version_of)
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


def test_builder_is_latest_defaults_true():
    req = _builder().with_location("s3://x", asset_type=AssetType.file).build()
    assert req.is_latest is True


def test_builder_custom_metadata_updates():
    """Test custom metadata behavior when updating sample, experiment, and data_summary sections."""
    # Build a registration with custom metadata at different levels
    req = (
        _builder()
        .with_location("s3://bucket/key", asset_type=AssetType.file)
        # Set initial sample metadata with custom field
        .with_sample(
            tissue=[
                TissueEntry(label="brain", ontology_id="UBERON:0000955", type=None)
            ],
            new_sample_field="added_later",
        )
        # Set initial experiment metadata with custom field
        .with_experiment(
            sub_modality="scRNA-seq",
            new_experiment_field="added_later",
        )
        # Set initial data_summary metadata with custom field
        .with_data_summary(
            read_length=150,
            new_data_summary_field="added_later",
        )
        # Add dataset-level custom metadata
        .with_custom_metadata(
            custom_dataset_field="dataset_value",
            project_metadata={"pi": "Dr. Smith", "grant": "R01-123456"},
        )
        .build()
    )

    # Verify final metadata state
    assert req.metadata.sample.organism is None
    assert req.metadata.sample.tissue[0].label == "brain"
    assert req.metadata.experiment.assay is None
    assert req.metadata.experiment.sub_modality == "scRNA-seq"
    assert req.metadata.data_summary.read_count is None
    assert req.metadata.data_summary.read_length == 150

    # Verify metadata contains only final values
    sample_dict = req.metadata.sample.model_dump()
    assert "custom_sample_field" not in sample_dict
    assert "sample_custom_metadata" not in sample_dict
    assert sample_dict["new_sample_field"] == "added_later"

    experiment_dict = req.metadata.experiment.model_dump()
    assert "custom_experiment_field" not in experiment_dict
    assert "experiment_custom_metadata" not in experiment_dict
    assert experiment_dict["new_experiment_field"] == "added_later"

    data_summary_dict = req.metadata.data_summary.model_dump()
    assert "custom_data_summary_field" not in data_summary_dict
    assert data_summary_dict["new_data_summary_field"] == "added_later"

    # Verify dataset-level custom metadata is preserved
    metadata_dict = req.metadata.model_dump()
    assert metadata_dict["custom_dataset_field"] == "dataset_value"
    assert metadata_dict["project_metadata"]["pi"] == "Dr. Smith"
    assert metadata_dict["project_metadata"]["grant"] == "R01-123456"


def test_builder_with_custom_metadata_only():
    """Test that with_custom_metadata works when setting only custom fields."""
    req = (
        _builder()
        .with_location("s3://bucket/key", asset_type=AssetType.file)
        .with_custom_metadata(
            custom_field="value1",
            metadata_object={"nested": "data"},
            flag=True,
        )
        .with_custom_metadata(
            custom_field="value2",  # Should override previous value
            additional_field="new_value",
        )
        .build()
    )

    metadata_dict = req.metadata.model_dump()
    assert metadata_dict["custom_field"] == "value2"  # Should be overridden
    assert metadata_dict["additional_field"] == "new_value"
    assert metadata_dict["metadata_object"]["nested"] == "data"  # Should be preserved
    assert metadata_dict["flag"] is True
