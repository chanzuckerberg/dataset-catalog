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

Reproducibility
---------------
The digest for a given piece of content does not depend on where it lives or
how it was obtained. A file hashes to the same value whether it is
checksummed on its own or as a child of a folder, and a checksum read from S3
metadata is directly comparable with one computed by downloading the object.
ChecksumResult.content_digest is the single field carrying that value.

Multipart composite checksums are the one thing S3 stores that cannot satisfy
this — they depend on the uploader's part size — so they are ignored rather
than mistaken for whole-object hashes.

Optional dependencies
---------------------
Install with the `checksum` extra: blake3 (for blake3), crcmod (for crc64),
awscrt (for crc64nvme). Each is imported lazily and raises ImportError only
when its algorithm is requested. boto3 is a required dependency of the package,
not part of this extra.

When no algorithm is given and nothing is stored on S3, `default_algorithm()`
picks blake3 if installed and otherwise blake2b (stdlib), so a base install
still produces checksums instead of failing.

Usage
-----
    from catalog_client.utils.checksum import compute_checksum, for_assets, Algorithm

    # Single path (local or S3)
    result = compute_checksum("data/file.h5ad", algorithm=Algorithm.blake3)
    result = compute_checksum("s3://my-bucket/prefix/", algorithm=Algorithm.crc32)

    # Batch asset list
    assets = for_assets(assets, algorithm=Algorithm.blake3)
"""

from catalog_client.utils.checksum.algorithm import Algorithm, default_algorithm
from catalog_client.utils.checksum.generate import (
    ChecksumWarning,
    for_assets,
    for_location,
)
from catalog_client.utils.checksum.hashing import compute_checksum
from catalog_client.utils.checksum.models import ChecksumResult, LocationChecksum

__all__ = [
    "Algorithm",
    "ChecksumResult",
    "LocationChecksum",
    "ChecksumWarning",
    "compute_checksum",
    "default_algorithm",
    "for_location",
    "for_assets",
]
