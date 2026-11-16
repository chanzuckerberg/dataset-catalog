"""Dataset instance models: each instance is one copy of a dataset's bytes."""

import datetime
import enum
from typing import Any

from pydantic import BaseModel, Field

from catalog_client.models.asset import (
    DataAssetRequest,
    DataAssetResponse,
    StoragePlatform,
)


class InstanceView(str, enum.Enum):
    """Which of a dataset's instances a dataset body carries.

    `default` is the primary, or on search/resolve the instances a location
    filter matched through. `filter` needs `storage_platform`, `root_uri`,
    or both.
    """

    default = "default"
    all = "all"
    filter = "filter"


class DatasetInstanceResponse(BaseModel):
    """One copy of a dataset: a root on one storage platform."""

    id: str = Field(description="Unique system-generated ID for this instance")
    created_at: datetime.datetime = Field(
        description="Timestamp when the instance was registered"
    )
    last_modified_at: datetime.datetime = Field(
        description="Timestamp when the instance was last updated"
    )
    tombstoned: bool = Field(description="Whether the instance has been removed")
    dataset_id: str = Field(description="ID of the dataset this is a copy of")
    root_uri: str = Field(
        description="Prefix every asset of this instance sits under, ending in one '/'"
    )
    storage_platform: StoragePlatform = Field(
        description="The one platform holding this instance"
    )
    is_primary: bool = Field(
        description="Whether this is the authoritative copy, the one a dataset write rewrites"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Free-form metadata about this copy"
    )


class DatasetInstanceWithLocationsResponse(DatasetInstanceResponse):
    locations: list[DataAssetResponse] = Field(
        default_factory=list,
        description="Assets this copy holds; equal relative_paths across instances are the same content",
    )


class DatasetInstanceListResponse(BaseModel):
    """Every instance of a dataset, primary first. Not paginated."""

    dataset_id: str = Field(description="ID of the dataset")
    results: list[DatasetInstanceWithLocationsResponse] = Field(
        description="The dataset's instances, primary first"
    )


class DatasetInstanceUpdate(BaseModel):
    """Assets to add to or update on one instance; omitted assets stay."""

    locations: list[DataAssetRequest] = Field(
        min_length=1,
        description="Matched by location_uri: a new URI is added, a known one updated. All must be on the instance's storage_platform",
    )
