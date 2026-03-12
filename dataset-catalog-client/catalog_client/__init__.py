# catalog_client package
# NOTE: This __init__.py is being rewritten. See Task 14 for the final version.
# The old imports are removed to allow the new models package to be built
# incrementally. The full public API will be re-exported after all tasks complete.

from catalog_client._context import get_client
from catalog_client.exceptions import AuthenticationError, CatalogError, CatalogServerError, NotFoundError

__all__ = [
    "get_client",
    "AuthenticationError",
    "CatalogError",
    "CatalogServerError",
    "NotFoundError",
]
