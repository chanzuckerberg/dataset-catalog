"""Data quality check results."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DataQualityChecks(BaseModel):
    model_config = ConfigDict(extra="allow")

    checks_passed: list[str] | None = Field(
        default=None, description="List of data quality checks that passed validation"
    )
    checks_failed: list[str] | None = Field(
        default=None, description="List of data quality checks that failed validation"
    )
    checks_skipped: list[str] | None = Field(
        default=None,
        description="List of data quality checks that were skipped or not applicable",
    )
