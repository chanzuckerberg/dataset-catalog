"""The filter list is spelled out in four places; these keep them agreeing.

Adding a filter means touching `iter_records`'s signature, `to_dataframe`'s
identical signature, the `filters` dict in `records.py`, and the route tuples in
`_route.py`. Miss the last one and the filter is accepted, ignored, and routed
wrong — silently, because `iter_datasets` reads by name from the dict.
"""

from __future__ import annotations

import inspect

from catalog_client.utils.dataframe import iter_records, to_dataframe
from catalog_client.utils.dataframe import records as records_module
from catalog_client.utils.dataframe._route import (
    LIST_ONLY_FILTERS,
    SEARCH_ONLY_FILTERS,
    SHARED_FILTERS,
)

FILTER_NAMES = frozenset(SEARCH_ONLY_FILTERS + LIST_ONLY_FILTERS + SHARED_FILTERS)
"""The route tuples are the single source of truth for what a filter is."""

SHAPING_PARAMS = frozenset(
    {
        "columns",
        "mapper",
        "rename",
        "list_sep",
        "exclude_tombstoned",
        "sort",
        "limit",
        "page_size",
    }
)
"""Everything in the signature that is not a filter. Add here when you add a
shaping argument — the point is that a *new filter* cannot slip in unnoticed."""


def _keyword_params(func: object) -> set[str]:
    return {
        name
        for name, param in inspect.signature(func).parameters.items()  # type: ignore[arg-type]
        if param.kind is inspect.Parameter.KEYWORD_ONLY
    }


def test_both_entry_points_accept_the_same_arguments():
    assert _keyword_params(iter_records) == _keyword_params(to_dataframe)


def test_every_non_shaping_parameter_is_a_known_filter():
    """A filter added to the signature but not to the route tuples would be
    accepted and then silently dropped."""
    assert _keyword_params(iter_records) - SHAPING_PARAMS == set(FILTER_NAMES)


def test_the_filters_dict_carries_exactly_the_known_filters(client, monkeypatch):
    """`_route.iter_datasets` looks filters up by name, so a key missing from
    the dict is not an error — it is a filter that stops working."""
    captured: dict[str, object] = {}

    def fake_iter_datasets(_client, filters, **_kwargs):
        captured.update(filters)
        return iter(())

    monkeypatch.setattr(records_module, "iter_datasets", fake_iter_datasets)

    list(iter_records(client, project="atlas"))

    assert set(captured) == set(FILTER_NAMES)


def test_the_route_tuples_do_not_overlap():
    """A name in two tuples would be sent to the server and filtered again
    client-side, or routed by one rule and applied by another."""
    assert len(FILTER_NAMES) == len(
        SEARCH_ONLY_FILTERS + LIST_ONLY_FILTERS + SHARED_FILTERS
    )
