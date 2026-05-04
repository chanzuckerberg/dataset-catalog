"""Collection models."""

from __future__ import annotations

import datetime
import enum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from catalog_client.models.dataset import DatasetResponse


class CollectionType(str, enum.Enum):
    publication = "publication"
    training = "training"


class CollectionChildType(str, enum.Enum):
    dataset = "dataset"
    collection = "collection"


class CollectionRequest(BaseModel):
    canonical_id: str = Field(
        description="Unique identifier for the collection across versions"
    )
    version: str = Field(description="Version string for the collection")
    name: str = Field(description="Human-readable name of the collection")
    collection_owner: str = Field(description="Owner or maintainer of the collection")
    description: str | None = Field(
        default=None, description="Detailed description of the collection"
    )
    license: str | None = Field(
        default=None, description="License under which the collection is made available"
    )
    doi: str | None = Field(
        default=None, description="Digital Object Identifier for the collection"
    )
    external_reference: str | None = Field(
        default=None, description="External URL or reference link for the collection"
    )
    collection_type: CollectionType | None = Field(
        default=None, description="Type of collection (publication or training)"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional metadata as key-value pairs"
    )


class CollectionResponse(CollectionRequest):
    id: str = Field(description="Unique system-generated ID for this collection")
    tombstoned: bool = Field(description="Whether the collection has been soft-deleted")
    created_at: datetime.datetime = Field(
        description="Timestamp when the collection was first created"
    )
    last_modified_at: datetime.datetime = Field(
        description="Timestamp when the collection was last updated"
    )
    collection_metadata: dict[str, Any] | None = Field(
        default=None, description="Additional metadata as key-value pairs"
    )


class DatasetEntryResponse(BaseModel):
    """A dataset child entry within a collection."""

    entry_type: Literal["dataset"] = "dataset"
    entry: DatasetResponse = Field(description="The dataset record")


class ChildCollectionEntryResponse(BaseModel):
    """A sub-collection child entry within a collection."""

    entry_type: Literal["collection"] = "collection"
    entry: CollectionResponse = Field(description="The collection record")


DatasetEntryResponse.model_rebuild(
    _types_namespace={
        "DatasetResponse": __import__(
            "catalog_client.models.dataset", fromlist=["DatasetResponse"]
        ).DatasetResponse,
    }
)
