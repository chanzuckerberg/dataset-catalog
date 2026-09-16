import pytest
from pydantic import ValidationError

from catalog_client.models.governance import (
    GovernanceMetadata,
    GovernanceMetadataResponse,
)
from catalog_client.models.metadata import (
    DatasetMetadata,
    ExperimentMetadata,
    OntologyEntry,
    SampleMetadata,
)
from catalog_client.models.quality import DataQualityChecks


def test_ontology_entry():
    entry = OntologyEntry(label="Homo sapiens", ontology_id="NCBITaxon:9606")
    assert entry.label == "Homo sapiens"


def test_sample_metadata_defaults_to_none():
    s = SampleMetadata()
    assert s.organism is None
    assert s.tissue is None


def test_experiment_metadata_assay_is_list_of_ontology_entry():
    e = ExperimentMetadata(
        assay=[OntologyEntry(label="10x Chromium", ontology_id="EFO:0009922")]
    )
    assert e.assay[0].label == "10x Chromium"
    assert e.assay[0].ontology_id == "EFO:0009922"


def test_dataset_metadata_nests_sub_models():
    m = DatasetMetadata(
        sample=SampleMetadata(
            organism=[OntologyEntry(label="Homo sapiens", ontology_id="NCBITaxon:9606")]
        ),
        experiment=ExperimentMetadata(
            assay=[OntologyEntry(label="scRNA-seq", ontology_id="EFO:0001187")]
        ),
    )
    assert m.sample.organism[0].label == "Homo sapiens"
    assert m.experiment.assay[0].label == "scRNA-seq"
    assert m.experiment.assay[0].ontology_id == "EFO:0001187"
    assert m.data_summary is None


def test_governance_metadata_extra_fields_allowed():
    g = GovernanceMetadata(
        data_steward="team-data", data_owner="team-x", custom_field="value"
    )
    assert g.data_owner == "team-x"
    assert g.model_extra["custom_field"] == "value"


def test_governance_requires_data_steward_on_write():
    with pytest.raises(ValidationError, match="data_steward"):
        GovernanceMetadata(data_owner="team-x")


def test_governance_response_tolerates_missing_data_steward():
    """Records written before schema v1.5.0 have no steward and must still parse."""
    g = GovernanceMetadataResponse.model_validate({"data_owner": "team-x"})
    assert g.data_steward is None


def test_data_quality_checks():
    q = DataQualityChecks(checks_passed=["format_check"], checks_failed=[])
    assert q.checks_passed == ["format_check"]
    assert q.checks_failed == []


def test_data_quality_carries_report_and_metric_assets():
    q = DataQualityChecks(
        report_assets=[{"name": "fastqc", "uri": "s3://bucket/qc/fastqc.html"}],
        metrics_assets=[{"name": "multiqc", "uri": "s3://bucket/qc/multiqc.json"}],
        metrics=[{"name": "duplication_rate", "value": 0.12}],
    )
    assert q.report_assets[0]["uri"] == "s3://bucket/qc/fastqc.html"
    assert q.metrics_assets[0]["name"] == "multiqc"
    assert q.metrics[0]["value"] == 0.12
    assert q.checks_skipped is None


def test_dataset_response_tolerates_null_project():
    """Rows written before schema v1.5.0 carry a NULL project and must still parse."""
    from catalog_client import DatasetResponse

    r = DatasetResponse.model_validate(
        {
            "id": "x",
            "canonical_id": "c",
            "version": "1.0.0",
            "project": None,
            "name": "n",
            "modality": "imaging",
            "governance": {},
            "metadata": {},
            "tombstoned": False,
            "created_at": "2026-01-01T00:00:00Z",
            "last_modified_at": "2026-01-01T00:00:00Z",
            "record_version": 1,
        }
    )
    assert r.project is None
