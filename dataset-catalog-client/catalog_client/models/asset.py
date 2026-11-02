"""Data asset models."""

import datetime
import enum

from pydantic import BaseModel, Field


class AssetType(str, enum.Enum):
    file = "file"
    folder = "folder"


class LocationScope(str, enum.Enum):
    """How a registered location counts as a match when resolving a URI.

    Matching is on whole path segments and is case-sensitive, so
    `s3://bkt/proj` never matches `s3://bkt/project-2`.
    """

    exact = "exact"
    ancestor = "ancestor"
    descendant = "descendant"


class StoragePlatform(str, enum.Enum):
    s3 = "s3"
    sf_hpc = "sf_hpc"
    chi_hpc = "chi_hpc"
    ny_hpc = "ny_hpc"
    reef = "reef"
    kelp = "kelp"
    atoll = "atoll"
    external = "external"
    other = "other"


class _DataAssetBase(BaseModel):
    """The fields the API carries wherever it describes a stored asset.

    Shared by `DataAssetRequest` and the copy route's `CopyEntry`: the API
    models those separately, but they describe the same thing and agree
    field for field, so the definitions live here rather than twice.
    """

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
    storage_platform: StoragePlatform = Field(
        description="Storage platform where the asset is located"
    )
    file_count: int | None = Field(
        default=None,
        description="Number of files in the asset (applicable for folders)",
    )


class DataAssetRequest(_DataAssetBase):
    """Asset fields supplied when creating or updating a dataset."""

    includes_pattern: str | None = Field(
        default=None,
        description="Glob pattern for files to include (applicable for folders)",
    )
    excludes_pattern: str | None = Field(
        default=None,
        description="Glob pattern for files to exclude (applicable for folders)",
    )


class DataAssetResponse(DataAssetRequest):
    # Lenient on parse: tolerate legacy/external assets returned without a
    # storage platform, even though it is required when creating an asset.
    # Intentionally widens the required request field; Pydantic allows the
    # override and responses are never submitted back as create requests.
    storage_platform: StoragePlatform | None = Field(  # type: ignore[assignment]
        default=None, description="Storage platform where the asset is located"
    )
    id: str = Field(description="Unique system-generated ID for this data asset")
    tombstoned: bool = Field(description="Whether the data asset has been soft-deleted")
    created_at: datetime.datetime = Field(
        description="Timestamp when the data asset was first created"
    )
    last_modified_at: datetime.datetime = Field(
        description="Timestamp when the data asset was last updated"
    )
    dataset_id: str = Field(description="ID of the dataset that this asset belongs to")
