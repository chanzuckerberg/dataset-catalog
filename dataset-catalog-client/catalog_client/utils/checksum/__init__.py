"""
Checksum utilities for local and S3 data assets.

.. warning::
    **Alpha feature.** This API is in alpha and may change without notice between releases.
    See docs/checksum_guide.md for usage examples.

Algorithms
----------
blake3, blake2b   cryptographic hashes; combined across chunks via Merkle tree.
crc32             stdlib zlib; multi-chunk composite matches S3 multipart model.
crc64             CRC64/ECMA-182 via crcmod; same composite model.
crc64nvme         AWS NVMe CRC64 via awscrt; natively verified by S3 on upload.

S3 natively checksums CRC32 and CRC64NVME. BLAKE3/BLAKE2b are client-side only.
For S3 uploads use ChecksumResult.s3_base64 — S3 expects base64, not hex.

Optional dependencies
---------------------
blake3, boto3, crcmod are required for checksum generation.
awscrt is only required for crc64nvme.

Usage
-----
    from catalog_client.utils.checksum import compute_checksum, for_assets, Algorithm

    # Single path (local or S3)
    result = compute_checksum("data/file.h5ad", algorithm=Algorithm.blake3)
    result = compute_checksum("s3://my-bucket/prefix/", algorithm=Algorithm.crc32)

    # Batch asset list
    assets = for_assets(assets, algorithm=Algorithm.blake3)
"""

from catalog_client.utils.checksum.algorithm import Algorithm
from catalog_client.utils.checksum.generate import ChecksumWarning, for_assets, for_location
from catalog_client.utils.checksum.hashing import compute_checksum
from catalog_client.utils.checksum.models import ChecksumResult, LocationChecksum

__all__ = [
    "Algorithm",
    "ChecksumResult",
    "LocationChecksum",
    "ChecksumWarning",
    "compute_checksum",
    "for_location",
    "for_assets",
]
