# catalog-client

Python client library for the Scientific Dataset Catalog API.

## Installation

```bash
pip install catalog-client
```

## Quick start

```python
from catalog_client import CatalogClient, DatasetModality, AssetType, OntologyEntry

with CatalogClient(base_url="https://your-catalog.example.com", api_token="your-token") as client:
    dataset_id = (
        client.new_registration(
            canonical_id="my-dataset",
            version="1.0.0",
            project="atlas",
            modality=DatasetModality.sequencing,
        )
        .named("My RNA-seq dataset")
        .with_location("s3://bucket/path/", asset_type=AssetType.folder)
        .with_governance(data_owner="my-team", is_pii=False)
        .with_sample(organism=[OntologyEntry(label="Homo sapiens", ontology_id="NCBITaxon:9606")])
        .submit()
    )
    print(dataset_id)
```

## Documentation

See [USAGE.md](USAGE.md) for the full usage guide covering datasets, collections, lineage,
async usage, and error handling.

An interactive walkthrough is available in [examples/quickstart.ipynb](examples/quickstart.ipynb). You can start up the jupyter notebook with the following command:

```commandline
uv run jupyter notebook examples/quickstart.ipynb
```
