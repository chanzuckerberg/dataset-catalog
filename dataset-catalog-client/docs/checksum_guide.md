# Checksum Generation — User Guide

> **Alpha Feature**
> The checksum API is in **alpha**. Interfaces may change without notice between releases.
> Pin your dependency to a specific version and review the changelog before upgrading.

---

## Installation

The package is installed directly from GitHub. The checksum feature requires the `checksum` extras group:

```bash
pip install "catalog-client[checksum] @ git+ssh://git@github.com/chanzuckerberg/dataset-catalog.git#subdirectory=dataset-catalog-client"
```

If you only need specific algorithms you can install their dependencies individually:

| Algorithm | Extra dependency |
|---|---|
| `blake3` | `pip install blake3` |
| `crc64` | `pip install crcmod` |
| `crc64nvme` | `pip install awscrt` |
| `crc32`, `blake2b` | No extra needed (stdlib) |

S3 access always requires `boto3` regardless of algorithm.

---

## Overview

The checksum module computes content hashes for data assets stored on S3 or the local filesystem.
It is designed to work with `DataAssetRequest` objects in the catalog client but can also be called
standalone via `for_location`.

Checksums are used to verify data integrity, detect changes between dataset versions, and deduplicate
equivalent files.

---

## Quick start

### Populate checksums on a list of assets

```python
import boto3
from catalog_client.utils.checksum import for_assets
from catalog_client.models.asset import DataAssetRequest, AssetType, StoragePlatform

assets = [
    DataAssetRequest(
        location_uri="s3://my-bucket/data/file.h5ad",
        asset_type=AssetType.file,
        storage_platform=StoragePlatform.s3,
    ),
    DataAssetRequest(
        location_uri="s3://my-bucket/data/folder/",
        asset_type=AssetType.folder,
        storage_platform=StoragePlatform.s3,
    ),
]

assets_with_checksums = for_assets(assets, s3_client=boto3.client("s3"))

for asset in assets_with_checksums:
    print(asset.location_uri, asset.checksum_alg, asset.checksum)
```

### Compute a checksum for a single location

```python
from catalog_client.utils.checksum import for_location
from catalog_client.models.asset import AssetType, StoragePlatform
import boto3

result = for_location(
    location_uri="s3://my-bucket/data/file.h5ad",
    asset_type=AssetType.file,
    storage_platform=StoragePlatform.s3,
    s3_client=boto3.client("s3"),
    compute_if_no_s3_checksum=True,
)

print(result.value)      # hex digest
print(result.algorithm)  # e.g. Algorithm.blake3
```

Note the default differs between the two entry points: `for_location` defaults to
`compute_if_no_s3_checksum=False`, so without the argument above it returns an empty
`LocationChecksum` (`value is None`) for an S3 object that has no stored checksum, rather
than downloading it. `for_assets` defaults to `True`. An empty result is falsy, so
`if result:` distinguishes the two cases.

---

## Supported algorithms

| Algorithm | Source | Notes |
|---|---|---|
| `blake3` | `blake3` package | Requires `pip install blake3` |
| `blake2b` | stdlib `hashlib` | Always available |
| `crc32` | stdlib `zlib` | Always available |
| `crc64` | `crcmod` package | Requires `pip install crcmod` |
| `crc64nvme` | `awscrt` package | Requires `pip install awscrt`; matches AWS CRC64NVME |

Pass an explicit algorithm with the `algorithm` parameter. When `algorithm=None` (the default),
the library auto-detects the best available algorithm from stored S3 checksums.

---

## S3 assets

### Algorithm auto-detection

When `algorithm=None`, the library inspects both S3 native checksum fields (`crc32`,
`crc64nvme`) and user metadata (`x-checksum-blake3`, `x-checksum-blake2b`,
`x-checksum-crc64`) in a single `HeadObject` call, then picks the strongest algorithm
present. Where a checksum was stored does not affect the choice — only which algorithm
it is, ranked by `ALGORITHM_PRIORITY` in `catalog_client/utils/checksum/s3.py`:

`blake3` > `blake2b` > `crc64` > `crc64nvme` > `crc32`

So a `blake3` value in user metadata is preferred over a native `crc32`. If no stored
checksum exists, `blake3` is used as the fallback and the object is downloaded to
compute the hash.

For folders, the algorithm must be present on **every** object under the prefix; the
strongest algorithm common to all children wins, and if there is no common algorithm the
folder falls back to `blake3`.

### Controlling downloads

By default, `for_assets` downloads and hashes objects that have no stored S3 checksum
(`compute_if_no_s3_checksum=True`). Set it to `False` to skip those assets instead of downloading:

```python
# Only use stored checksums; skip assets that have none
assets_with_checksums = for_assets(
    assets,
    compute_if_no_s3_checksum=False,
    s3_client=boto3.client("s3"),
)
```

Assets skipped this way are returned unchanged (no `checksum` or `checksum_alg` set).

### Explicit algorithm

Pass an explicit algorithm to force a specific hash. The library first checks whether a stored
checksum for that algorithm already exists on the S3 object; if so it uses it without downloading.
If not, it downloads and computes:

```python
from catalog_client.utils.checksum import for_assets, Algorithm

assets_with_checksums = for_assets(
    assets,
    algorithm=Algorithm.crc32,
    s3_client=boto3.client("s3"),
)
```

### Folders (S3 prefix)

Pass `asset_type=AssetType.folder` and a URI ending in `/`. The library lists all objects under
the prefix, hashes each file, then produces a Merkle tree digest that represents the entire folder.
The `checksum` on the returned asset is the Merkle root — it changes whenever any file in the
folder changes.

```python
folder_asset = DataAssetRequest(
    location_uri="s3://my-bucket/dataset/",
    asset_type=AssetType.folder,
    storage_platform=StoragePlatform.s3,
)
result = for_assets([folder_asset], s3_client=boto3.client("s3"))
```

---

## Local filesystem assets

Use any non-S3 storage platform (for example `StoragePlatform.sf_hpc`) and provide an
absolute path. No S3 client is needed, and `compute_if_no_s3_checksum` has no effect —
local paths are always hashed.

```python
from catalog_client.utils.checksum import Algorithm, for_location
from catalog_client.models.asset import AssetType, StoragePlatform

result = for_location(
    location_uri="/data/local-file.h5ad",
    asset_type=AssetType.file,
    storage_platform=StoragePlatform.sf_hpc,
    algorithm=Algorithm.blake3,
)
```

Directories are hashed recursively in the same way as S3 folders.

---

## Unsupported platforms

Assets with `StoragePlatform.external` or `StoragePlatform.other` are not supported.
`for_location` returns an empty `LocationChecksum` and emits a `ChecksumWarning`.
`for_assets` passes those assets through unchanged.

---

## Error handling

Failures during checksum computation are caught and surfaced as `ChecksumWarning` (not raised
exceptions), so a single bad asset does not abort the whole batch. The asset is returned unchanged.

To surface errors more aggressively, attach a warnings filter:

```python
import warnings
from catalog_client.utils.checksum import ChecksumWarning

with warnings.catch_warnings():
    warnings.simplefilter("error", ChecksumWarning)
    for_assets(assets, s3_client=s3)
```

---

## Caching

`for_assets` maintains an internal `cached_results` dict across assets in the same batch.
If multiple assets share files (e.g. overlapping S3 prefixes), each file is only hashed once.

You can also pass a pre-populated `cached_results` dict to `for_location` to share a cache across
multiple calls:

```python
from catalog_client.models.asset import AssetType, StoragePlatform
from catalog_client.utils.checksum import ChecksumResult, for_location

cache: dict[str, ChecksumResult] = {}

for uri in uris:
    result = for_location(
        uri,
        asset_type=AssetType.file,
        storage_platform=StoragePlatform.s3,
        s3_client=s3,
        cached_results=cache,
    )
```
