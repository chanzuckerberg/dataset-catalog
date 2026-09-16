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
        description="Classification level of data sensitivity: 'Low', 'Medium' or 'High'. Descriptive only; filter on access_scope instead",
    )
    access_scope: str | None = Field(
        default=None,
        description="Gates record visibility: exactly 'internal' (the server default) or 'public'. Any other string is lowercased and stored rather than rejected, so a typo hides the record from the filter everyone searches with",
    )
    is_pii: bool | None = Field(
        default=None,
        description="Whether the dataset contains Personally Identifiable Information",
    )
    is_phi: bool | None = Field(
        default=None,
        description="Whether the dataset contains Protected Health Information",
    )
    data_steward: str = Field(
        description="Required. Person or org that defines the standards and best practices for the data's accuracy, quality and completeness, and ingests and formats datasets to meet them",
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
    # Lenient on parse: `data_steward` became required in schema v1.5.0, but records
    # written under earlier versions were stored without one and are still returned.
    # The API makes the same allowance — its response model types governance as a bare
    # dict. Intentionally widens a required request field; responses are never
    # submitted back as create requests.
    data_steward: str | None = Field(  # type: ignore[assignment]
        default=None,
        description="Person or org responsible for the data's accuracy, quality and completeness. Absent on records written before schema v1.5.0",
    )
