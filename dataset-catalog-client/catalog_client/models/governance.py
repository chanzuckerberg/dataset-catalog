"""Governance and access-control metadata."""

from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict


class GovernanceMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    license: str | None = None
    data_sensitivity: str | None = None
    access_scope: str | None = None
    is_pii: bool | None = None
    is_phi: bool | None = None
    data_steward: str | None = None
    data_owner: str | None = None
    is_external_reference: bool | None = None
    embargoed_until: datetime.date | None = None
