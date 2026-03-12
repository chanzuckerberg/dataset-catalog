"""Data quality check results."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DataQualityChecks(BaseModel):
    model_config = ConfigDict(extra="allow")

    checks_passed: list[str] | None = None
    checks_failed: list[str] | None = None
    checks_skipped: list[str] | None = None
