"""Dot-notation metadata field extraction with list expansion.

The implementation lives in :mod:`catalog_client.utils._extract` because the
dataframe utility needs the same path syntax.  This module re-exports it so
existing manifest imports keep working.
"""

from __future__ import annotations

from catalog_client.utils._extract import _extract_metadata_field

__all__ = ["_extract_metadata_field"]
