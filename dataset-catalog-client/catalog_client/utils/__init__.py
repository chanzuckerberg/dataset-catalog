"""Utility modules for catalog client."""

# The checksum entry points (for_assets, for_location, compute_checksum) are
# deliberately NOT re-exported here: those names say nothing about checksums
# once they sit beside the manifest helpers. Import them from their own
# namespace instead:
#
#     from catalog_client.utils.checksum import for_assets
#
# The types below are re-exported because they are checksum-specific by name
# and appear in user annotations and warning filters.
from catalog_client.utils.checksum import (
    Algorithm,
    ChecksumResult,
    ChecksumWarning,
    LocationChecksum,
)
from catalog_client.utils.manifest import (
    FieldFilter,
    FilterCondition,
    ManifestFormat,
    ManifestResult,
    ManifestStats,
    MetadataFieldSpec,
    generate_manifest,
    generate_manifest_iter,
    write_manifest,
)

__all__ = [
    # Checksums
    "Algorithm",
    "ChecksumResult",
    "ChecksumWarning",
    "LocationChecksum",
    # Manifest
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
