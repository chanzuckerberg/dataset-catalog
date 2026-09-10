"""API page-size ceilings, and the client policies derived from them.

Collected here so a ceiling that moves server-side is edited in one place
rather than found by grep. Several of these are equal today by coincidence
rather than because they are the same fact — the hydrated-search cap and the
collection-entry cap are both 100, but they belong to different routes and can
diverge, so they are named separately and consumers import the one they mean.

Provenance: these mirror what the client has enforced since the cursor-paging
work (7abef97), not a reading of the live spec. `/openapi.json` may sit behind
SSO, so they have not been re-verified against it here. Treat them as the
client's current assertion and confirm against `/api/meta/openapi.json` before
relying on one for anything load-bearing.

Only ceilings with a consumer are declared. The lineage and audit-log routes
also cap at 100, but nothing checks them yet — see `lineages.py`, whose
`limit` arguments are unvalidated — so naming them here would add constants no
code reads.

Note that the two dataset-route policies differ: an oversized `limit` on
`datasets.list()`/`search()` raises, while `collections_.py` silently clamps
to `COLLECTION_MAX_LIMIT`. That predates this module and is left alone here.

Keep this module free of intra-package imports. The sub-clients import it
during `catalog_client/__init__.py`'s own execution, so anything it pulled back
in from the package would be a circular import.
"""

from __future__ import annotations

__all__ = [
    "COLLECTION_MAX_LIMIT",
    "DATASET_LIST_MAX_LIMIT",
    "DATASET_MAX_OFFSET",
    "DATASET_SEARCH_HYDRATED_MAX_LIMIT",
    "DATASET_SEARCH_MAX_LIMIT",
]

DATASET_SEARCH_MAX_LIMIT = 1000
"""Largest page `GET /api/datasets/search/` accepts."""

DATASET_LIST_MAX_LIMIT = 500
"""Largest page `GET /api/datasets/` accepts."""

DATASET_SEARCH_HYDRATED_MAX_LIMIT = 100
"""Largest page `search(hydrate=True)` accepts.

`hydrate=True` re-reads every hit from the database, so the server caps the
page size well below the 1000 an unhydrated search allows.
"""

COLLECTION_MAX_LIMIT = 100
"""Largest page the collection routes accept, including `list_entries()`.

The dataset routes were raised past this by the keyset-paging work; the
collection routes were not.
"""

DATASET_MAX_OFFSET = 10_000
"""Depth past which the client refuses offset paging, in favour of a cursor.

A client policy, not a server ceiling: the server accepts deeper offsets, but
it walks and discards every skipped row, and a concurrent write shifts the
window — so rows get skipped or repeated. A cursor is constant-cost at any
depth and immune to that shift.
"""
