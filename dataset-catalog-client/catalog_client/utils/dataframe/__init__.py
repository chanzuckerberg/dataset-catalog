"""DataFrame package.

Pulls catalog datasets into a flat table, one row per dataset, choosing
between the list route and the hydrated search route from the filters given.
"""

from catalog_client.utils.dataframe._columns import DEFAULT_COLUMNS
from catalog_client.utils.dataframe._types import ColumnSpec, RecordMapper
from catalog_client.utils.dataframe.frame import to_dataframe
from catalog_client.utils.dataframe.records import iter_records

# COMPUTED_COLUMNS is deliberately not re-exported: it is a mutable dict of
# implementation detail, and the columns it registers are requested by name
# ("asset_count", "total_size_bytes") like any other. See the package README.

__all__ = [
    "DEFAULT_COLUMNS",
    "ColumnSpec",
    "RecordMapper",
    "iter_records",
    "to_dataframe",
]
