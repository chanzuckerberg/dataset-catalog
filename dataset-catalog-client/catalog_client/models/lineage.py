"""Lineage edge models."""

from __future__ import annotations

import datetime
import enum
from typing import Any

from pydantic import BaseModel, Field


class LineageType(str, enum.Enum):
    version_of = "version_of"
    transformed_from = "transformed_from"
    copy_of = "copy_of"


class LineageEdgeRequest(BaseModel):
    source_dataset_id: str = Field(
        description="ID of the source dataset in the lineage relationship"
    )
    destination_dataset_id: str = Field(
        description="ID of the destination dataset in the lineage relationship"
    )
    lineage_type: LineageType = Field(
        description="Type of lineage relationship (version_of, transformed_from, copy_of)"
    )
    source_data_asset_id: str | None = Field(
        default=None,
        description="Specific data asset ID within the source dataset (optional)",
    )
    destination_data_asset_id: str | None = Field(
        default=None,
        description="Specific data asset ID within the destination dataset (optional)",
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional metadata about the lineage relationship"
    )


class LineageEdgeResponse(LineageEdgeRequest):
    id: str = Field(description="Unique system-generated ID for this lineage edge")
    tombstoned: bool = Field(
        description="Whether the lineage edge has been soft-deleted"
    )
    created_at: datetime.datetime = Field(
        description="Timestamp when the lineage edge was first created"
    )
    last_modified_at: datetime.datetime = Field(
        description="Timestamp when the lineage edge was last updated"
    )
