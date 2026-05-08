"""Governance and access-control metadata."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict, Field


class GovernanceMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    license: str | None = Field(
        default=None,
        description="License under which the dataset is made available. This can either be the name of the license like 'MIT' or a link to the term of agreement",
    )
    data_sensitivity: str | None = Field(
        default=None,
        description="Classification level of data sensitivity (e.g., 'low', 'medium', 'high', 'extremely high')",
    )
    access_scope: str | None = Field(
        default=None,
        description="Scope of access permissions (e.g., 'public', 'internal', 'private')",
    )
    is_pii: bool | None = Field(
        default=None,
        description="Whether the dataset contains Personally Identifiable Information",
    )
    is_phi: bool | None = Field(
        default=None,
        description="Whether the dataset contains Protected Health Information",
    )
    data_steward: str | None = Field(
        default=None,
        description="Person or group responsible for data stewardship and quality",
    )
    data_owner: str | None = Field(
        default=None, description="Person or organization that owns the data"
    )
    is_external_reference: bool = Field(
        default=False,
        description="Whether this dataset references external data hosted by a third part, and not stored locally",
    )
    embargoed_until: datetime.date | None = Field(
        default=None,
        description="Date until which the dataset is under embargo/restricted access",
    )
