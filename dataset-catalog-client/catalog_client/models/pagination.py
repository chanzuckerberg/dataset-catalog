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


class CursorPaginatedResponse(BaseModel, Generic[T]):
    """A page that can be walked by either keyset cursor or offset.

    `total` is null when the request passed `include_total=False`, and on a
    cursor walk it is the count taken on page 1 rather than a per-page
    recount. `offset` is null on a cursor walk.
    """

    limit: int = Field(description="Maximum number of items returned in this response")
    results: list[T] = Field(description="List of items for this page")
    total: int | None = Field(
        default=None,
        description=(
            "Total number of items available, or None when the count was skipped"
        ),
    )
    offset: int | None = Field(
        default=None,
        description="Number of items skipped, or None when paging by cursor",
    )
    next_cursor: str | None = Field(
        default=None,
        description=(
            "Cursor for the next page; None once the last page has been reached"
        ),
    )
