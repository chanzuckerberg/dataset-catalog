"""Helpers shared by more than one utility package.

Everything else under ``catalog_client/utils/`` is a feature package with a
user-facing surface — ``checksum``, ``dataframe``, ``manifest``.  This one is
not: it exists so a helper needed by two of them has a home that belongs to
neither, instead of living in whichever package happened to need it first.
Dot-path extraction started inside ``manifest`` and had to be lifted out when
``dataframe`` needed the same traversal; ``commons`` is where the next one
goes directly.

The bar is that the *implementation* serves more than one package, which is
not the same as every exported name having two callers.  It does not here:
``dataframe`` parses a path once and applies it per record
(``parse_path`` + ``extract_path``), while ``manifest`` takes the one-shot
``extract_field``, which is a wrapper over the same two.  One traversal, two
entry points shaped to their callers.  Read that split as intended rather than
as evidence a symbol is unused.

What does not belong here: a helper with a single caller, which stays in that
caller's package, and anything with a user-facing surface, which earns a
feature package of its own.

Deliberately not re-exported from ``catalog_client.utils`` or the top-level
package: nothing here is public API, and the names are meaningless without the
context of the caller that needs them.
"""

from catalog_client.utils.commons._extract import (
    PathSegments,
    extract_field,
    extract_path,
    parse_path,
)

__all__ = [
    "PathSegments",
    "extract_field",
    "extract_path",
    "parse_path",
]
