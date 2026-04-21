from catalog_client.models.governance import GovernanceMetadata
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
    g = GovernanceMetadata(data_owner="team-x", custom_field="value")
    assert g.data_owner == "team-x"
    assert g.model_extra["custom_field"] == "value"


def test_data_quality_checks():
    q = DataQualityChecks(checks_passed=["format_check"], checks_failed=[])
    assert q.checks_passed == ["format_check"]
    assert q.checks_failed == []
    assert q.checks_skipped is None
