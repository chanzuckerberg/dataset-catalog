import os

from catalog_client import CatalogClient
from catalog_client.utils.manifest import (
    MetadataFieldSpec,
    generate_manifest,
    write_manifest,
)

CATALOG_API_TOKEN = os.getenv("CATALOG_API_TOKEN")
CATALOG_API_URL = os.getenv(
    "CATALOG_API_URL", "https://datacatalog.staging-sci-data.staging.czi.team/"
)


def _log_progress(datasets_processed: int) -> None:
    if datasets_processed % 100 == 0:
        print(f"  processed {datasets_processed} datasets...")


def generate(collection_id: str, file_path: str) -> None:
    client = CatalogClient(CATALOG_API_URL, CATALOG_API_TOKEN)
    result = generate_manifest(
        client,
        collection_id=collection_id,
        metadata_fields=[
            MetadataFieldSpec("manifest_group_id"),
            MetadataFieldSpec("split"),
            MetadataFieldSpec("experiment.sub_modality", alias="sub_modality"),
            MetadataFieldSpec("experiment.assay[].label", alias="assay_labels"),
        ],
        on_progress=_log_progress,
    )

    if not result:
        print("No assets found for this collection.")
        return

    print(
        f"Manifest: {result.stats.total_rows} rows "
        f"from {result.stats.total_datasets} datasets "
        f"({result.stats.skipped_tombstoned_datasets} tombstoned skipped, "
        f"{result.stats.skipped_filtered_assets} filtered out)"
    )

    write_manifest(result, file_path)


if __name__ == "__main__":
    if not CATALOG_API_TOKEN:
        raise ValueError("CATALOG_API_TOKEN environment variable is not set")

    generate("019e1b55-3933-756e-bb97-056b2ae39fcb", "EVICAN.csv")
