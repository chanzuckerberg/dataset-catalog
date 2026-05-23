"""Manifest generation package.

Generates a flat, asset-level manifest from a catalog collection.
"""

from catalog_client.utils.manifest._types import (
    FieldFilter,
    FilterCondition,
    ManifestResult,
    ManifestStats,
    MetadataFieldSpec,
)
from catalog_client.utils.manifest.generate import (
    generate_manifest,
    generate_manifest_iter,
)
from catalog_client.utils.manifest.write import ManifestFormat, write_manifest

__all__ = [
    "FieldFilter",
    "FilterCondition",
    "ManifestFormat",
    "ManifestResult",
    "ManifestStats",
    "MetadataFieldSpec",
    "generate_manifest",
    "generate_manifest_iter",
    "write_manifest",
]
