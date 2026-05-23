"""Dot-notation metadata field extraction with list expansion."""

from __future__ import annotations

from typing import Any


def _extract_metadata_field(metadata: dict[str, Any], path: str) -> Any:
    """Extract a value from a metadata dict using dot-notation with list expansion.

    A segment ending with ``[]`` signals that the value at that key is a list;
    the remaining path is applied to each item and the results are returned as a
    list.  Any missing intermediate key returns ``None`` without raising.

    Examples::

        # metadata = {"sample": {"organism": [{"label": "Homo sapiens"}]}}
        _extract_metadata_field(metadata, "sample.organism[].label")
        # → ["Homo sapiens"]

        _extract_metadata_field(metadata, "experiment.sub_modality")
        # → "confocal"  (or None if absent)
    """
    segments = path.split(".")
    current: Any = metadata

    for i, segment in enumerate(segments):
        if current is None:
            return None

        is_list_expand = segment.endswith("[]")
        key = segment[:-2] if is_list_expand else segment

        if not isinstance(current, dict):
            return None
        current = current.get(key)

        if is_list_expand:
            if not isinstance(current, list):
                return None
            remaining = ".".join(segments[i + 1 :])
            if not remaining:
                return current
            return [
                _extract_metadata_field(item, remaining)
                if isinstance(item, dict)
                else None
                for item in current
            ]

    return current
