"""Data asset models."""

from __future__ import annotations

import datetime
import enum

from pydantic import BaseModel, Field


class AssetType(str, enum.Enum):
    file = "file"
    folder = "folder"


class StoragePlatform(str, enum.Enum):
    s3 = "s3"
    sf_hpc = "sf_hpc"
    chi_hpc = "chi_hpc"
    ny_hpc = "ny_hpc"
    reef = "reef"
    kelp = "kelp"
    external = "external"
    other = "other"


class DataAssetRequest(BaseModel):
    """Asset fields supplied when creating or updating a dataset."""

    location_uri: str = Field(
        description="URI or path to the data asset (file or directory)"
    )
    asset_type: AssetType = Field(description="Whether the asset is a file or folder")
    encoding: str | None = Field(
        default=None, description="Text encoding of the asset (e.g., 'utf-8')"
    )
    size_bytes: int | None = Field(
        default=None, description="Size of the asset in bytes"
    )
    checksum: str | None = Field(
        default=None, description="Checksum hash value for data integrity verification"
    )
    checksum_alg: str | None = Field(
        default=None,
        description="Algorithm used to compute the checksum (e.g., 'md5', 'sha256')",
    )
    file_format: str | None = Field(
        default=None,
        description="Format or type of the file (e.g., 'csv', 'parquet', 'tiff')",
    )
    description: str | None = Field(
        default=None, description="Human-readable description of the asset"
    )
    storage_platform: StoragePlatform | None = Field(
        default=None, description="Storage platform where the asset is located"
    )
    file_count: int | None = Field(
        default=None,
        description="Number of files in the asset (applicable for folders)",
    )
    includes_pattern: str | None = Field(
        default=None,
        description="Glob pattern for files to include (applicable for folders)",
    )
    excludes_pattern: str | None = Field(
        default=None,
        description="Glob pattern for files to exclude (applicable for folders)",
    )


class DataAssetResponse(DataAssetRequest):
    id: str = Field(description="Unique system-generated ID for this data asset")
    tombstoned: bool = Field(description="Whether the data asset has been soft-deleted")
    created_at: datetime.datetime = Field(
        description="Timestamp when the data asset was first created"
    )
    last_modified_at: datetime.datetime = Field(
        description="Timestamp when the data asset was last updated"
    )
    dataset_id: str = Field(description="ID of the dataset that this asset belongs to")
