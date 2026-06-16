"""Data quality check results."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DataQualityChecks(BaseModel):
    model_config = ConfigDict(extra="allow")

    checks_passed: list[Any] | None = Field(
        default=None, description="List of data quality checks that passed validation"
    )
    checks_failed: list[Any] | None = Field(
        default=None, description="List of data quality checks that failed validation"
    )
    checks_skipped: list[Any] | None = Field(
        default=None,
        description="List of data quality checks that were skipped or not applicable",
    )
