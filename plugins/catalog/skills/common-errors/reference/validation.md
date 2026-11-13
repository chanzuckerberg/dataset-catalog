# Validation (local or 422)

| Error text | Cause | Fix | See |
|---|---|---|---|
| `<path>: Field required` | A required field or block is missing (`governance`, `metadata`, `locations`, `governance.data_steward`, …) | Supply it; for governance, ask the user | field-reference |
| `governance.is_pii: Input should be a valid boolean` (also `is_phi`) | `null` in `mapping.json`: not yet answered | Get the answer from the user; never default to `false` | registration-script |
| `<path>: Input should be '<a>', '<b>' or '<c>'` | Value outside the allowed set | Map the source value onto an allowed one | field-reference |
| `'<x>' is not a valid DatasetModality` (or `StoragePlatform`, `DatasetType`, …) | Enum built from an unmapped or `null` source value | Map it explicitly; for `None is not a valid StoragePlatform`, fill `assets.storage_platform` in `mapping.json` | field-reference |
| `<uri> cannot be registered: <reason>` (script) / `locations.<n>.location_uri: not registrable, <reason>` (validator) | Asset points at a local disk, temp dir, home directory, or a bare path on a non-cluster platform | Register the copy on shared storage; never a local stand-in | concepts |
| `locations: List should have at least 1 item after validation, not 0` | No assets built | Fix `build_assets` | registration-script |
| `<path>: Extra inputs are not permitted (not in the schema; the API would drop it)` | Misspelt or unknown key (from `validate_record.py`; pydantic would silently drop it) | Use the real field name | field-reference |
| `<root>: Input should be a valid dictionary` | Payload is not a JSON object | Validate one record object per file | — |
| `Unknown facet field(s): [<x>]. Allowed: [<…>].` (422) | Facet name not supported | Use one from the list in the message | search |
| `Input should be greater than or equal to 1` on `limit` (422) | `limit=0` | Use a limit within the route's range | search |
| `limit must be <= <n> on <route>, got <m>` / `limit must be >= 1` | SDK refused an out-of-range page size before sending | Same | search |
