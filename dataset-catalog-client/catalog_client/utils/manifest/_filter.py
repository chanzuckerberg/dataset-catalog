"""Asset-level filter evaluation against :class:`FilterCondition` operator dicts."""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


def _cmp_op(fn: Callable[[Any, Any], bool]) -> Callable[[Any, Any], bool]:
    """Wrap a comparison into a safe evaluator with consistent exclude semantics.

    Returns ``False`` (asset excluded) when the field value is ``None`` or when
    the comparison raises :exc:`TypeError` (e.g. comparing a string to an int).
    This matches the silent-exclude behaviour of the string operators.
    """

    def _check(v: Any, o: Any) -> bool:
        if v is None:
            return False
        try:
            return fn(v, o)
        except TypeError:
            return False

    return _check


# o is already the coerced type (frozenset for in_/nin_) when coming from FieldFilter.
_CHECKS: dict[str, Callable[[Any, Any], bool]] = {
    "eq_": lambda v, o: v == o,
    "in_": lambda v, o: v in o,
    "nin_": lambda v, o: v not in o,
    "startswith_": lambda v, o: isinstance(v, str) and v.startswith(o),
    "endswith_": lambda v, o: isinstance(v, str) and v.endswith(o),
    "contains_": lambda v, o: isinstance(v, str) and o in v,
    "gt_": _cmp_op(lambda a, b: a > b),
    "gte_": _cmp_op(lambda a, b: a >= b),
    "lt_": _cmp_op(lambda a, b: a < b),
    "lte_": _cmp_op(lambda a, b: a <= b),
}


class FieldFilter(BaseModel):
    """Operator spec for a single asset field."""

    model_config = ConfigDict(extra="forbid")

    eq_: Any = None
    in_: frozenset[Any] | None = None
    nin_: frozenset[Any] | None = None
    startswith_: str | None = None
    endswith_: str | None = None
    contains_: str | None = None
    gt_: Any = None
    gte_: Any = None
    lt_: Any = None
    lte_: Any = None

    @field_validator("in_", "nin_", mode="before")
    @classmethod
    def _to_frozenset(cls, v: Any) -> frozenset[Any] | None:
        return frozenset(v) if v is not None else None

    def matches(self, value: Any) -> bool:
        """Return ``True`` if *value* satisfies every explicitly-set operator."""
        for op in self.model_fields_set:
            if not _CHECKS[op](value, getattr(self, op)):
                return False
        return True


FilterCondition = dict[str, FieldFilter]
"""Maps asset field names to :class:`FieldFilter` operator specs (all must pass — AND logic)."""


def _asset_matches(asset: dict[str, Any], filter_condition: FilterCondition) -> bool:
    """Return ``True`` if the asset satisfies every :class:`FieldFilter` (AND logic)."""
    for field, ff in filter_condition.items():
        if not isinstance(ff, FieldFilter):
            try:
                ff = FieldFilter.model_validate(ff)
            except ValidationError as exc:
                extra = [
                    str(e["loc"][0])
                    for e in exc.errors()
                    if e["type"] == "extra_forbidden"
                ]
                op = extra[0] if extra else str(exc)
                raise ValueError(f"Unknown filter operator: {op!r}") from exc
        if not ff.matches(asset.get(field)):
            return False
    return True
