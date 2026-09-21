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
    report_assets: list[dict[str, str]] | None = Field(
        default=None,
        description="Human-readable QC reports, one entry per file, as {'name': ..., 'uri': ...} (e.g. {'name': 'fastqc', 'uri': 's3://bucket/qc/fastqc.html'}). Pointers only; the catalog never fetches or hosts them",
    )
    metrics_assets: list[dict[str, str]] | None = Field(
        default=None,
        description="Machine-readable metric files backing the checks, one entry per file, as {'name': ..., 'uri': ...} (e.g. {'name': 'multiqc', 'uri': 's3://bucket/qc/multiqc_data.json'})",
    )
    metrics: list[dict[str, Any]] | None = Field(
        default=None,
        description="Metric values inline, one entry per metric with at least a name and value (e.g. {'name': 'duplication_rate', 'value': 0.12}); use for the few worth reading without opening a file, and put the bulk in metrics_assets",
    )
