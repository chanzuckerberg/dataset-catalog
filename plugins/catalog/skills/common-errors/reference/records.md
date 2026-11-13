# Records and lineage

| Error text | Cause | Fix | See |
|---|---|---|---|
| `Dataset already exists: DatasetRef<…>. Use update_if_exists=True to update or error_on_duplicate=False to skip.` | `register()` / `submit()` called with defaults on a re-run | Call `register(request, update_if_exists=True, error_on_duplicate=False)` (the template does) | registration-script |
| `update_if_exists and error_on_duplicate cannot both be True` | Both flags set | `update_if_exists=True` needs `error_on_duplicate=False` | registration-script |
| `Multiple datasets found (<n>) for DatasetRef<…>` | Several live records share one signature | Stop; list them (`catalog list …`) and have the owner resolve it | search |
| `Could not resolve DatasetRef(canonical_id=…, version=…, project=…): …` | Lineage parent not registered (or wrong coordinates) | Register the parent first, or fix the reference | concepts |
| `Dataset '<id>' not found` (404) | Wrong or tombstoned id, or a `canonical_id` passed where a UUID is needed | Look the record up again; resolve coordinates through the list route | search |
| `Dataset 'resolve' not found` | The deployment predates `datasets/resolve` (the path fell through to the by-id route) | Use `catalog list` by coordinates; not evidence the URI is unregistered | search |
| `Pass either \`cursor\` or \`offset\`, not both.` (400) | Both paging styles sent | Use one | search |
| HTTP 409 creating a lineage edge | The API refused the edge as conflicting with an existing one | List edges for the pair; do not retry blindly | concepts |
| HTTP 503 from search | Search backend unavailable | Retry once later, then report; never substitute guesses | search |
