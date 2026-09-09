"""The page-size ceilings are declared once and derived from, not restated.

Before `catalog_client.limits` existed, `100` was declared independently in
`client/datasets.py`, `utils/manifest/generate.py` and
`utils/dataframe/_route.py`. They were equal by coincidence — a hydrated-search
ceiling, a collection-entry ceiling and a client policy — so raising one
server-side would have left the other two silently stale.
"""

from __future__ import annotations

from catalog_client import limits
from catalog_client.client import datasets as datasets_client
from catalog_client.utils.dataframe import _route as dataframe_route
from catalog_client.utils.manifest import generate as manifest_generate


def test_the_dataset_client_uses_the_declared_ceilings():
    assert datasets_client._LIST_MAX_LIMIT == limits.DATASET_LIST_MAX_LIMIT
    assert datasets_client._SEARCH_MAX_LIMIT == limits.DATASET_SEARCH_MAX_LIMIT
    assert (
        datasets_client._HYDRATED_MAX_LIMIT == limits.DATASET_SEARCH_HYDRATED_MAX_LIMIT
    )
    assert datasets_client._MAX_OFFSET == limits.DATASET_MAX_OFFSET


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
        limits.DATASET_MAX_OFFSET,
    }
    # The hydrated/collection ceiling (100) is excluded: it is also the default
    # `limit` on several routes, where it is a starting page size rather than a
    # restatement of the maximum.

    offenders = []
    for path in package.rglob("*.py"):
        if path.name == "limits.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                if node.value.value in ceilings:
                    names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                    offenders.append(f"{path.name}: {names} = {node.value.value}")

    assert not offenders, (
        f"these look like ceilings restated outside catalog_client.limits: {offenders}"
    )
