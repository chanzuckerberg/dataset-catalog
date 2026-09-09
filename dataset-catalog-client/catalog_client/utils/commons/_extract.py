"""Dot-notation field extraction with list expansion.

Shared by the manifest and dataframe utilities, which both need to pull a
value out of a nested response dict given a path written by the caller.

A path is parsed once into segments by :func:`parse_path` and applied many
times by :func:`extract_path`.  Callers that extract the same path from every
record in a walk should parse it once and keep the segments;
:func:`_extract_metadata_field` is the convenience form that does both.
"""

from __future__ import annotations

from typing import Any, Tuple

PathSegments = Tuple[Tuple[str, bool, "int | None"], ...]
"""A parsed dot-path: one ``(key, expands_list, index)`` triple per segment.

``index`` is the integer form of *key* when the segment is a positional index
into a list, and ``None`` otherwise, so neither the ``[]`` suffix nor the
digit test is recomputed per record.
"""


def parse_path(path: str) -> PathSegments:
    """Split a dot-path into segments, resolving the syntax once.

    Examples::

        parse_path("sample.organism[].label")
        # → (("sample", False, None), ("organism", True, None),
        #    ("label", False, None))

        parse_path("data_summary.dimension.0")
        # → (("data_summary", False, None), ("dimension", False, None),
        #    ("0", False, 0))
    """
    segments = []
    for segment in path.split("."):
        is_list_expand = segment.endswith("[]")
        key = segment[:-2] if is_list_expand else segment
        segments.append((key, is_list_expand, int(key) if key.isdigit() else None))
    return tuple(segments)


def extract_path(value: Any, segments: PathSegments) -> Any:
    """Walk *segments* into *value*, returning ``None`` on any mismatch.

    See :func:`_extract_metadata_field` for the path syntax.
    """
    current: Any = value

    for position, (key, is_list_expand, index) in enumerate(segments):
        if current is None:
            return None

        if isinstance(current, list):
            # A positional index is the only thing that can follow a list; a
            # dict key here means the path does not match the data's shape.
            if index is None or index >= len(current):
                return None
            current = current[index]
        elif isinstance(current, dict):
            current = current.get(key)
        else:
            return None

        if is_list_expand:
            if not isinstance(current, list):
                return None
            remaining = segments[position + 1 :]
            if not remaining:
                return current
            return [
                extract_path(item, remaining) if isinstance(item, dict) else None
                for item in current
            ]

    return current


def _extract_metadata_field(metadata: dict[str, Any], path: str) -> Any:
    """Extract a value from a nested dict using dot-notation with list expansion.

    A segment ending with ``[]`` signals that the value at that key is a list;
    the remaining path is applied to each item and the results are returned as a
    list.  An all-digit segment indexes into a list positionally.  Any missing
    intermediate key, out-of-range index, or type mismatch returns ``None``
    without raising.

    Parses *path* on every call.  In a loop over records, call
    :func:`parse_path` once and :func:`extract_path` per record instead.

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
    return extract_path(metadata, parse_path(path))
