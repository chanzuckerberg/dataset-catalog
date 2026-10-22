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
        description="Classification level of data sensitivity: 'Low', 'Medium' or 'High'",
    )
    access_scope: str | None = Field(
        default=None,
        description="Gates record visibility: exactly 'internal' (the server default) or 'public'",
    )
    is_pii: bool = Field(
        description="Required. Whether the dataset contains Personally Identifiable Information. 'I am not sure' is not False — ask your data steward before you write",
    )
    is_phi: bool = Field(
        description="Required. Whether the dataset contains Protected Health Information",
    )
    data_steward: str = Field(
        description="Required. Person or org that defines the standards and best practices for the data's accuracy, quality and completeness, and ingests and formats datasets to meet them",
    )
    data_generator: str | list[str] | None = Field(
        default=None,
        description="Person, lab or org that produced the data. Pass a list when more than one party generated it",
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


class GovernanceMetadataResponse(GovernanceMetadata):
    """Response-side governance, as `DatasetResponse.governance`.

    `data_steward` is required on write but tolerated as `None` on read: records
    written before schema v1.5.0 made it required were stored without one and are
    still returned, and they were never counted, so a read must not fail on them.
    The API widens exactly this field on its own `GovernanceResponse`.

    `is_pii` / `is_phi` are *not* widened. No stored record is missing either — the
    count covered nulls, not just absent keys — so a response without them signals a
    defect and should fail here rather than read back as a record whose sensitivity
    the caller cannot determine.
    """

    data_steward: str | None = Field(  # type: ignore[assignment]
        default=None,
        description="Person or org responsible for the data's accuracy, quality and completeness",
    )
