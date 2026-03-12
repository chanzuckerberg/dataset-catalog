"""Lineage edge models."""
from __future__ import annotations

import datetime
import enum
from typing import Any

from pydantic import BaseModel


class LineageType(str, enum.Enum):
    version_of = "version_of"
    transformed_from = "transformed_from"
    copy_of = "copy_of"


class LineageEdgeCreate(BaseModel):
    source_dataset_id: str
    destination_dataset_id: str
    lineage_type: LineageType
    source_data_asset_id: str | None = None
    destination_data_asset_id: str | None = None
    metadata: dict[str, Any] | None = None


class LineageEdgeResponse(BaseModel):
    id: str
    tombstoned: bool
    created_at: datetime.datetime
    created_by: str | None
    last_modified_at: datetime.datetime
    modified_by: str | None
    source_dataset_id: str
    destination_dataset_id: str
    lineage_type: LineageType
    source_data_asset_id: str | None = None
    destination_data_asset_id: str | None = None
    lineage_metadata: dict[str, Any] | None
