"""Collection models."""

from __future__ import annotations

import datetime
import enum
from typing import Any

from pydantic import BaseModel


class CollectionType(str, enum.Enum):
    publication = "publication"
    training = "training"


class CollectionCreate(BaseModel):
    canonical_id: str
    version: str
    name: str
    collection_owner: str
    description: str | None = None
    license: str | None = None
    doi: str | None = None
    collection_type: CollectionType | None = None
    metadata: dict[str, Any] | None = None


class CollectionUpdate(BaseModel):
    canonical_id: str | None = None
    version: str | None = None
    name: str | None = None
    collection_owner: str | None = None
    description: str | None = None
    license: str | None = None
    doi: str | None = None
    collection_type: CollectionType | None = None
    metadata: dict[str, Any] | None = None


class CollectionResponse(BaseModel):
    id: str
    tombstoned: bool
    created_at: datetime.datetime
    last_modified_at: datetime.datetime
    canonical_id: str
    version: str
    name: str
    collection_owner: str
    description: str | None = None
    license: str | None = None
    doi: str | None = None
    collection_type: CollectionType | None = None
    collection_metadata: dict[str, Any] | None
