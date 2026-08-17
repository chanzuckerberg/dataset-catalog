# Checksum Generation — User Guide

> **Alpha Feature**
> The checksum API is in **alpha**. Interfaces may change without notice between releases.
> Pin your dependency to a specific version and review the changelog before upgrading.

---

## Migrating from `catalog_client.utils.checksums`

**This release removes the old module.** There is no compatibility shim.

| Before | Now |
|---|---|
| `from catalog_client.utils.checksums import generate_for_assets` | `from catalog_client.utils.checksum import for_assets` |
| `from catalog_client.utils.checksums import ChecksumWarning` | `from catalog_client.utils.checksum import ChecksumWarning` |
| `get_supported_algorithms()` → `list[str]` | iterate the `Algorithm` enum |
| `algorithm="blake3"` (str) | `algorithm=Algorithm.blake3` (strings still work — `Algorithm` is a `StrEnum`) |
| `algorithm="blake2s"` | no longer supported; use `Algorithm.blake2b` |
| implicit `boto3.client("s3")` | pass `s3_client=` explicitly (still auto-created if omitted) |

Also note:

- `for_assets` returns **copies**; it no longer relies on you reading the objects you passed in.
- The checksum entry points are no longer re-exported from `catalog_client.utils`.
  Import them from `catalog_client.utils.checksum`.
- Folder assets (`AssetType.folder`) are now supported; they used to be skipped.

Public names were removed without a deprecation cycle. This ships as a normal feature
release rather than a major bump: the checksum API is alpha, and alpha interfaces are
expected to break between releases (see the note at the top of this guide). Pin an exact
version if you depend on these imports.

---

## Reproducibility guarantees

The digest for a given piece of content does not depend on where that content lives
or how it was reached:

- A file hashes to the same value whether it is checksummed on its own or as a child
  of a folder.
- The same bytes at two different paths, or in two different buckets, hash the same.
- A checksum read from S3 (native or user metadata) is directly comparable with one
  computed by downloading the object.
- Local and S3 copies of the same bytes agree.

`ChecksumResult.content_digest` is the single field carrying that value; it is what
`for_location` and `for_assets` report, and what a child contributes to its parent
folder's Merkle root.

Two deliberate exceptions:

- **Folder digests include child names**, so renaming a file changes its folder's
  digest even though no content changed. This is what makes a folder digest useful
  for change detection.
- **Multipart composite checksums are ignored.** When S3 reports a composite value
  (`ChecksumType: COMPOSITE`, or a `-N` part-count suffix), it is a checksum over the
  part checksums, not over the object's bytes — its value depends on the part size the
  uploader chose. Such values are skipped rather than mistaken for whole-object
  hashes, and the object is hashed normally instead.

Stored values that are not well-formed digests for their algorithm — wrong width, or
not hex — are ignored for the same reason, since they could not be combined into a
folder digest.

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
    print(asset.location_uri, asset.checksum_alg, asset.checksum, asset.size_bytes)
```

`for_assets` fills in `size_bytes` alongside the checksum. See
[Asset sizes](#asset-sizes) for when it is and is not written.

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

print(result.value)       # hex digest
print(result.algorithm)   # e.g. Algorithm.blake3
print(result.total_size)  # bytes, or None if the platform did not report one
```

Both entry points default to `compute_if_no_s3_checksum=True`, so an S3 object with no
stored checksum is downloaded and hashed. Set it to `False` on either to skip such
objects instead. An empty result is falsy, so `if result:` distinguishes the two cases.
A size alone never makes a result truthy — `total_size` is ignored by that check.

### From the command line

The installed `catalog` script exposes the same machinery as `catalog checksum PATH`,
for one local path or S3 URI at a time. It needs no catalog URL or token — only AWS
credentials, and only for `s3://` paths.

```bash
catalog checksum data/file.h5ad
catalog checksum data/folder/ --children
catalog checksum s3://my-bucket/data/file.h5ad            # reuses a stored checksum
catalog checksum s3://my-bucket/data/file.h5ad --recompute
catalog checksum data/file.h5ad --algorithm crc32 -o json  # full ChecksumResult
catalog checksum data/folder/ --workers 1                  # serial, for comparison
```

Like `for_location`, omitting `--algorithm` lets a checksum already stored on the S3
object decide the algorithm, so nothing is downloaded. The table's `SOURCE` column
reports which path was taken (`computed`, `s3_native`, `s3_metadata`), and `-o json`
adds the fields the Python API exposes as properties: `content_digest`, `s3_base64`,
and `s3_composite_base64` (files only). See the [CLI section of
USAGE.md](../USAGE.md#checksums-from-the-command-line) for every flag and the exit
codes.

---

## Asset sizes

Every checksum result carries `total_size`, the number of bytes it covers, and
`for_assets` copies it onto each asset's `size_bytes`.

The size is read from the storage platform, never counted while hashing:

| Path | Source |
|---|---|
| Local file | `os.fstat` on the open handle |
| Local directory | sum over all descendants |
| S3 object with a stored checksum | `ContentLength` on the `HeadObject` response |
| S3 object being downloaded | `ContentLength` on the `GetObject` response |
| S3 folder | `Size` on the `ListObjectsV2` listing, summed over children |

Two consequences follow. It costs no extra API calls or I/O — every value above rides on a
request the library already makes. And it is reported even when a stored S3 checksum means
the object is never read, which is the common case for data uploaded through S3 (AWS
attaches a CRC32 to every upload).

`total_size` is `None`, not `0`, when the platform did not report a size — a 0-byte file
reports `0`. A directory whose child size is unknown reports `None` rather than an
understated sum.

Two rules govern `size_bytes` on assets:

- **A caller-supplied size wins.** `for_assets` only writes `size_bytes` where it is `None`.
- **Size follows the checksum.** If an asset is skipped — unsupported platform,
  `compute_if_no_s3_checksum=False` with nothing stored, or an error — neither `checksum`
  nor `size_bytes` is set.

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

When nothing is stored and no algorithm is named, `default_algorithm()` decides: `blake3`
if the `checksum` extra is installed, otherwise `blake2b` from the standard library. A base
install therefore still produces checksums rather than failing — and since the algorithm is
always recorded in `checksum_alg`, values stay self-describing. Pass `algorithm=` explicitly
if you need the same algorithm regardless of what is installed.

`crc64` is CRC-64/ECMA-182 (polynomial `0x42F0E1EBA9EA3693`, non-reflected;
`CRC64("123456789") == 0x6C40DF5F0B497347`).

---

## S3 assets

### Algorithm auto-detection

When `algorithm=None`, the library inspects both S3 native checksum fields (`crc32`,
`crc64nvme`) and user metadata (`x-checksum-blake3`, `x-checksum-blake2b`,
`x-checksum-crc64`) in a single `HeadObject` call.

**For a single file**, it picks the highest-priority algorithm present, ranked by
`ALGORITHM_PRIORITY` in `catalog_client/utils/checksum/s3.py`:

`crc64nvme` > `crc32` > `blake3` > `blake2b` > `crc64`

S3-native algorithms rank first: they are what S3 computes and can verify itself, so
reusing one keeps the catalog digest comparable with what the platform reports. Where a
checksum was stored does not otherwise affect the choice. If no stored checksum exists,
`default_algorithm()` is used and the object is downloaded to compute the hash.

**For a folder**, the algorithm does *not* have to be present on every object. The
library ranks candidates by how much recompute each would need — the bytes and the
number of objects that lack it — and picks the cheapest. Children that already carry the
chosen algorithm contribute their stored digest; only the rest are downloaded. Priority
breaks ties, which in practice means two algorithms that both need no downloads at all.

Mixing stored and computed digests is safe: a child hashed locally produces the same
value it would report as a stored checksum, so the folder digest is identical either
way. If no child carries anything readable, the folder falls back to
`default_algorithm()` and every object is downloaded.

> **Digest width.** Selection optimises for recompute cost and does not impose a minimum
> digest strength, so a prefix where `crc32` has better coverage than the alternatives
> will be registered with a 32-bit digest. Distinct 32-bit values collide at around 65k
> objects by the birthday bound. Pass an explicit `algorithm=` where that matters.

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

The flag governs **downloads**, not folders as such. A folder whose children all carry a
stored checksum is still assembled, because doing so needs no download — and that holds
whether the algorithm was named explicitly or discovered by auto-detection.

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

Pass `asset_type=AssetType.folder`. The library lists all objects under the prefix, hashes
each file, then produces a Merkle tree digest representing the entire folder. The `checksum`
on the returned asset is that root — it changes whenever any file in the folder changes, or
is added, removed, or renamed.

A trailing `/` on the URI is optional: `asset_type` decides how the location is treated, and
the prefix is normalised internally so that `s3://bucket/ds` and `s3://bucket/ds/` produce the
same digest and neither sweeps in a sibling prefix such as `s3://bucket/ds2/`.

```python
folder_asset = DataAssetRequest(
    location_uri="s3://my-bucket/dataset/",
    asset_type=AssetType.folder,
    storage_platform=StoragePlatform.s3,
)
result = for_assets([folder_asset], s3_client=boto3.client("s3"))
```

The folder's `size_bytes` is the sum of every file under the prefix, taken from the same
listing used to enumerate them.

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

**Every** skip and failure goes through `ChecksumWarning` — including an empty `location_uri`,
an unsupported or missing `storage_platform`, and a missing `s3_client` for an S3 asset. So a
single warnings filter catches all of them:

```python
import warnings
from catalog_client.utils.checksum import ChecksumWarning

with warnings.catch_warnings():
    warnings.simplefilter("error", ChecksumWarning)
    for_assets(assets, s3_client=s3)
```

Errors reading stored checksums are **not** silently absorbed. A `HeadObject` that fails with
an access, credential, or throttling error is reported (as a `ChecksumWarning` via the batch
handler) rather than being treated as "this object has no stored checksum" — which would have
quietly triggered a full download, or a silent skip under `compute_if_no_s3_checksum=False`.
Only a genuinely missing object counts as "no stored checksum".

---

## Parallelism

Folders are hashed concurrently by default. `max_workers` (`--workers` on the CLI)
caps the threads; `None` picks a default from the available CPUs and `1` forces the
serial path.

**It never changes a checksum.** A folder digest depends on the order children are
*combined* in, which stays sorted by name regardless of the order they finish in. The
eval's `parallelism` dimension asserts this for every tree shape, every algorithm and
several worker counts, per path rather than only at the root.

What it does and does not speed up:

| workload | effect |
|---|---|
| S3 folder | Large. Per-object `HeadObject` and `GetObject` calls are issued concurrently, so cost goes from one round trip per object to roughly one per worker's worth. |
| Local folder of large files | 2–4.5x, measured. blake3 3.9x, blake2b 4.5x, crc32 2.3x, crc64nvme 2.1x on 8 × 8MB. |
| Local folder of many small files | Unchanged. The pool only engages above a mean file size, because below it the cost is `open`/`close` in the kernel rather than hashing, and threads measured net-negative. |
| Single file | Unchanged — there is nothing to parallelise across. |

Two things stay serial deliberately, both because measurement said so: directory
listing (concurrency made it monotonically worse on a local filesystem), and the
per-asset loop in `for_assets` (so every `ChecksumWarning` is raised on the calling
thread, keeping the contract under `warnings.simplefilter("error", ChecksumWarning)`).

```python
# Cap threads, or force the serial path.
assets = for_assets(assets, s3_client=s3, max_workers=4)
result = compute_checksum_localfs("/data/folder", Algorithm.blake3, max_workers=1)
```

If you pass your own `s3_client`, the S3 worker count is clamped to its
`max_pool_connections` (10 on a stock client). Exceeding that pool does not queue —
botocore discards and re-opens connections instead — so raise it on the client if you
want more concurrency than that:

```python
import boto3
from botocore.config import Config

s3 = boto3.client("s3", config=Config(max_pool_connections=32))
assets = for_assets(assets, s3_client=s3, max_workers=32)
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
