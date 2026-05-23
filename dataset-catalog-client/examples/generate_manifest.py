import csv
import os

from catalog_client import CatalogClient
from catalog_client.utils.manifest import generate_manifest

CATALOG_API_TOKEN = os.getenv("CATALOG_API_TOKEN")
CATALOG_API_URL = "https://datacatalog.staging-sci-data.staging.czi.team/"


def generate(collection_id: str, file_path: str):
    client = CatalogClient(CATALOG_API_URL, CATALOG_API_TOKEN)
    result = generate_manifest(
        client,
        collection_id=collection_id,
        metadata_fields=[
            "experiment.sub_modality",
            "experiment.assay[].label",
            "manifest_group_id",
            "split",
        ],
    )

    if not result:
        return
    with open(file_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=result[0].keys())
        writer.writeheader()
        writer.writerows(result)


if __name__ == "__main__":
    if not CATALOG_API_TOKEN:
        raise ValueError("CATALOG_API_TOKEN not set for env")

    print(os.getcwd())
    generate("019e1b55-3933-756e-bb97-056b2ae39fcb", "EVICAN.csv")
