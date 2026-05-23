"""Asset-level filter evaluation against :class:`FilterCondition` operator dicts."""

from __future__ import annotations

from typing import Any

from catalog_client.utils.manifest._types import FilterCondition


def _asset_matches(asset: dict[str, Any], filter_condition: FilterCondition) -> bool:
    """Return True if the asset satisfies every :class:`FieldFilter` (AND logic)."""
    for field, operators in filter_condition.items():
        value = asset.get(field)

        op: str
        operand: Any
        for op, operand in operators.items():
            if op == "eq_":
                if value != operand:
                    return False
            elif op == "in_":
                if value not in operand:
                    return False
            elif op == "nin_":
                if value in operand:
                    return False
            elif op == "startswith_":
                if not (isinstance(value, str) and value.startswith(operand)):
                    return False
            elif op == "endswith_":
                if not (isinstance(value, str) and value.endswith(operand)):
                    return False
            elif op == "contains_":
                if not (isinstance(value, str) and operand in value):
                    return False
            elif op == "gt_":
                if value is None or value <= operand:
                    return False
            elif op == "gte_":
                if value is None or value < operand:
                    return False
            elif op == "lt_":
                if value is None or value >= operand:
                    return False
            elif op == "lte_":
                if value is None or value > operand:
                    return False
            else:
                raise ValueError(f"Unknown filter operator: {op!r}")

    return True
