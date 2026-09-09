"""Helpers shared by more than one utility package.

Everything else under ``catalog_client/utils/`` is a feature package with a
user-facing surface — ``checksum``, ``dataframe``, ``manifest``.  This one is
not: it exists so a helper needed by two of them has a home that belongs to
neither, instead of living in whichever package happened to need it first.
Dot-path extraction started inside ``manifest`` and had to be lifted out when
``dataframe`` needed the same traversal; ``commons`` is where the next one
goes directly.

The bar for adding something here is that a second package already needs it.
A helper with one caller belongs in that caller's package, and anything with a
user-facing surface belongs in a feature package of its own.

Deliberately not re-exported from ``catalog_client.utils`` or the top-level
package: nothing here is public API, and the names are meaningless without the
context of the caller that needs them.
"""

from catalog_client.utils.commons._extract import (
    PathSegments,
    _extract_metadata_field,
    extract_path,
    parse_path,
)

__all__ = [
    "PathSegments",
    # Underscore-prefixed and still exported: the name predates the move and
    # renaming it is a separate change, but the symbol is genuinely shared.
    "_extract_metadata_field",
    "extract_path",
    "parse_path",
]
