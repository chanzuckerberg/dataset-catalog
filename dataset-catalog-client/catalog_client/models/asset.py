"""Data asset models."""

from __future__ import annotations

import datetime
import enum

from pydantic import BaseModel


class AssetType(str, enum.Enum):
    file = "file"
    folder = "folder"


class StoragePlatform(str, enum.Enum):
    s3 = "s3"
    bruno_hpc = "bruno hpc"
    hpc = "hpc"
    coreweave = "coreweave"
    external = "external"
    other = "other"


class DataAssetRequest(BaseModel):
    """Asset fields supplied when creating or updating a dataset."""

    location_uri: str
    asset_type: AssetType
    encoding: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    checksum_alg: str | None = None
    file_format: str | None = None
    description: str | None = None
    storage_platform: StoragePlatform | None = None
    file_count: int | None = None
    includes_pattern: str | None = None
    excludes_pattern: str | None = None


class DataAssetResponse(BaseModel):
    id: str
    tombstoned: bool
    created_at: datetime.datetime
    last_modified_at: datetime.datetime
    location_uri: str
    asset_type: AssetType
    encoding: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    checksum_alg: str | None = None
    file_format: str | None = None
    description: str | None = None
    storage_platform: StoragePlatform | None = None
    file_count: int | None = None
    includes_pattern: str | None = None
    excludes_pattern: str | None = None
    dataset_id: str
