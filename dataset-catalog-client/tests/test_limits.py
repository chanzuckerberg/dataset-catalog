"""The page-size ceilings are declared once and derived from, not restated.

Before `catalog_client.limits` existed, `100` was declared independently in
`client/datasets.py`, `utils/manifest/generate.py` and
`utils/dataframe/_route.py`. They were equal by coincidence — a hydrated-search
ceiling, a collection-entry ceiling and a client policy — so raising one
server-side would have left the other two silently stale.
"""

from __future__ import annotations

from catalog_client import limits
from catalog_client.utils.dataframe import _route as dataframe_route
from catalog_client.utils.manifest import generate as manifest_generate


def test_the_dataframe_page_size_tracks_the_hydrated_search_ceiling():
    """to_dataframe applies one cap to both routes, so it must be the lower of
    the two — otherwise a search-routed query would ask for more than the
    server allows."""
    assert dataframe_route.MAX_PAGE_SIZE == limits.DATASET_SEARCH_HYDRATED_MAX_LIMIT
    assert dataframe_route.MAX_PAGE_SIZE <= limits.DATASET_LIST_MAX_LIMIT


def test_the_manifest_page_size_tracks_the_collection_ceiling():
    """The manifest walk pages collections.list_entries(), not the dataset
    routes, so it must not follow the dataset ceilings upward."""
    assert manifest_generate._MAX_PAGE_SIZE == limits.COLLECTION_MAX_LIMIT


def test_no_ceiling_is_restated_as_a_literal_outside_limits():
    """A grep would catch this too, but only if someone thought to run it."""
    import ast
    import pathlib

    package = pathlib.Path(limits.__file__).parent
    ceilings = {
        limits.DATASET_LIST_MAX_LIMIT,
        limits.DATASET_SEARCH_MAX_LIMIT,
        limits.DATASET_SEARCH_HYDRATED_MAX_LIMIT,
        limits.COLLECTION_MAX_LIMIT,
        limits.DATASET_MAX_OFFSET,
    }
    # Only `NAME = <int literal>` assignments are checked. A default
    # `limit: int = 100` in a route signature is a starting page size, not a
    # restatement of the maximum, and is not an `ast.Assign` anyway. The type
    # check is load-bearing: `100.0 == 100` in Python, so a float constant
    # like s3.py's `_NETWORK_MB_S = 100.0` would otherwise match a ceiling.

    offenders = []
    for path in package.rglob("*.py"):
        if path.name == "limits.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                value = node.value.value
                if type(value) is int and value in ceilings:
                    names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                    offenders.append(f"{path.name}: {names} = {node.value.value}")

    assert not offenders, (
        f"these look like ceilings restated outside catalog_client.limits: {offenders}"
    )
