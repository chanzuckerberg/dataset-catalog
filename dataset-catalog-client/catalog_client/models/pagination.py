"""Generic paginated response wrapper."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    total: int = Field(description="Total number of items available across all pages")
    limit: int = Field(description="Maximum number of items returned in this response")
    offset: int = Field(description="Number of items skipped before these results")
    results: list[T] = Field(description="List of items for this page")
