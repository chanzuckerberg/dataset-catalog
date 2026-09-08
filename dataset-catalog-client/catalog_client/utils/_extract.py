"""Dot-notation field extraction with list expansion.

Shared by the manifest and dataframe utilities, which both need to pull a
value out of a nested response dict given a path written by the caller.
"""

from __future__ import annotations

from typing import Any


def _extract_metadata_field(metadata: dict[str, Any], path: str) -> Any:
    """Extract a value from a nested dict using dot-notation with list expansion.

    A segment ending with ``[]`` signals that the value at that key is a list;
    the remaining path is applied to each item and the results are returned as a
    list.  An all-digit segment indexes into a list positionally.  Any missing
    intermediate key, out-of-range index, or type mismatch returns ``None``
    without raising.

    Examples::

        # metadata = {"sample": {"organism": [{"label": "Homo sapiens"}]}}
        _extract_metadata_field(metadata, "sample.organism[].label")
        # → ["Homo sapiens"]

        _extract_metadata_field(metadata, "experiment.sub_modality")
        # → "confocal"  (or None if absent)

        # metadata = {"data_summary": {"dimension": [512, 512, 40]}}
        _extract_metadata_field(metadata, "data_summary.dimension.0")
        # → 512
    """
    segments = path.split(".")
    current: Any = metadata

    for i, segment in enumerate(segments):
        if current is None:
            return None

        is_list_expand = segment.endswith("[]")
        key = segment[:-2] if is_list_expand else segment

        if isinstance(current, list):
            # A positional index is the only thing that can follow a list; a
            # dict key here means the path does not match the data's shape.
            if not key.isdigit():
                return None
            index = int(key)
            if index >= len(current):
                return None
            current = current[index]
        elif isinstance(current, dict):
            current = current.get(key)
        else:
            return None

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
