# Manifest Generation

Generates a flat, asset-level manifest from a catalog collection.  Each row
corresponds to one data asset (file or folder location) from one dataset.
Datasets with multiple locations produce multiple rows that share the same
dataset-level fields.

---

## User guide

### Quick start

```python
from catalog_client import CatalogClient
from catalog_client.utils.manifest import MetadataFieldSpec, generate_manifest

client = CatalogClient(base_url="https://catalog.example.com", api_token="...")

result = generate_manifest(
    client,
    collection_id="019e1b55-3933-756e-bb97-056b2ae39fcb",
    metadata_fields=[
        MetadataFieldSpec("experiment.sub_modality", alias="modality"),
        MetadataFieldSpec("sample.organism[].label", alias="organisms"),
        MetadataFieldSpec("split"),   # no alias — key is "split"
    ],
)

print(f"{result.stats.total_rows} rows from {result.stats.total_datasets} datasets")
for row in result:
    print(row["location_uri"], row["modality"])
```

### Fixed fields in every row

| Field | Source |
|---|---|
| `dataset_id` | Dataset UUID |
| `canonical_id` | Human-readable dataset identifier |
| `version` | Dataset version string |
| `record_version` | Incrementing edit counter |
| `location_uri` | Asset URI (e.g. `s3://bucket/path`) |
| `storage_platform` | Platform enum value (e.g. `s3`) |
| `checksum` | Asset checksum value |
| `checksum_alg` | Algorithm used (e.g. `blake3`) |

Additional columns come from `metadata_fields`.

---

### Specifying metadata fields — `MetadataFieldSpec`

```python
# Path only — output column name equals the path
MetadataFieldSpec("split")

# Path + alias — output column name is the alias
MetadataFieldSpec("experiment.sub_modality", alias="modality")

# List expansion — use [] on the segment whose value is a list
MetadataFieldSpec("sample.organism[].label", alias="organisms")
# → {"organisms": ["Homo sapiens", "Mus musculus"]}
```

If a path resolves to `None` for every row a `UserWarning` is issued — this
usually indicates a typo in the path.

---

### Filtering assets — `FilterCondition`

`filter_condition` is a `dict[str, FieldFilter]` that constrains which asset
rows appear in the manifest.  All conditions must pass (AND logic).

```python
filter_condition={
    # String operators
    "location_uri": {"endswith_": ".tiff"},
    "location_uri": {"startswith_": "s3://imaging-bucket"},
    "location_uri": {"contains_": "/raw/"},

    # Membership operators
    "storage_platform": {"in_": ["s3", "gcs"]},
    "asset_type":       {"nin_": ["folder"]},

    # Equality
    "record_version": {"eq_": 1},

    # Numeric / comparable operators
    "record_version": {"gte_": 2},
    "record_version": {"lt_": 10},
}
```

| Operator | Matches when… |
|---|---|
| `eq_` | value equals operand (str or numeric) |
| `in_` | value is in the operand list |
| `nin_` | value is not in the operand list |
| `startswith_` | string value starts with operand |
| `endswith_` | string value ends with operand |
| `contains_` | string value contains operand |
| `gt_` | value > operand |
| `gte_` | value >= operand |
| `lt_` | value < operand |
| `lte_` | value <= operand |

---

### Reading stats — `ManifestStats`

`generate_manifest` returns a `ManifestResult` with a `stats` attribute:

```python
result = generate_manifest(client, collection_id)

print(result.stats.total_datasets)             # datasets visited
print(result.stats.skipped_tombstoned_datasets) # excluded due to tombstone
print(result.stats.skipped_tombstoned_assets)   # assets excluded due to tombstone
print(result.stats.skipped_filtered_assets)     # assets excluded by filter_condition
print(result.stats.total_rows)                  # rows in the manifest
```

`ManifestResult` also supports list-like access for backwards compatibility:

```python
bool(result)     # False if empty
len(result)      # number of rows
result[0]        # first row dict
list(result)     # all rows as a plain list
```

---

### Streaming large collections — `generate_manifest_iter`

For large collections where buffering all rows in memory is undesirable, use
the streaming variant:

```python
from catalog_client.utils.manifest import generate_manifest_iter

for row in generate_manifest_iter(client, collection_id, metadata_fields=[...]):
    process(row)   # rows arrive page by page, never all in memory at once
```

`generate_manifest_iter` accepts the same parameters as `generate_manifest`
except it yields `dict` rows instead of returning a `ManifestResult`.

---

### Progress reporting

Both functions accept an `on_progress` callback invoked after each dataset is
visited (whether or not it produced rows):

```python
def log_progress(datasets_processed: int) -> None:
    if datasets_processed % 100 == 0:
        print(f"  processed {datasets_processed} datasets...")

result = generate_manifest(client, collection_id, on_progress=log_progress)
```

---

### Recursing into child collections

Collections can contain other collections as children.  Pass `recurse=True` to
traverse the full hierarchy.  Cycle detection prevents infinite loops:

```python
result = generate_manifest(client, collection_id, recurse=True)
```

---

### Page size

The API caps pages at 100 entries.  Passing a higher value issues a
`UserWarning` and the value is clamped automatically:

```python
result = generate_manifest(client, collection_id, page_size=50)  # fine
result = generate_manifest(client, collection_id, page_size=500) # warns, uses 100
```

---

### Export to CSV

```python
import csv

result = generate_manifest(client, collection_id, metadata_fields=[...])

with open("manifest.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=result.rows[0].keys())
    writer.writeheader()
    writer.writerows(result.rows)
```

---

## Developer guide

### Package layout

```
catalog_client/utils/manifest/
├── __init__.py     # re-exports the full public surface
├── _types.py       # FieldFilter, FilterCondition, MetadataFieldSpec,
│                   # ManifestStats, ManifestResult
├── _extractor.py   # _extract_metadata_field  — dot-notation traversal
├── _filter.py      # _asset_matches           — FieldFilter evaluation
├── _iterator.py    # _iter_entries            — pagination + recursion generator
└── generate.py     # generate_manifest, generate_manifest_iter — public API
```

### Dependency flow

```
_types.py
   ↑
_extractor.py   _filter.py (_types)
         ↖     ↗
          _iterator.py (_types, _extractor, _filter)
               ↑
           generate.py (_types, _iterator)
               ↑
           __init__.py (re-exports _types + generate)
```

No module imports from `__init__.py` or upward — the flow is strictly
bottom-up with no cycles.

---

### How `_iter_entries` works

`_iter_entries` is the single internal generator shared by both public
functions.  When called:

1. Fetches one page of collection entries via `client.collections.list_entries`.
2. For each **dataset entry**: extracts metadata fields, iterates asset
   locations, applies tombstone exclusion and filter conditions, and yields
   matching rows.
3. For each **collection entry** (when `recurse=True`): recurses into the child
   collection, guarded by a `_visited` set to prevent cycles.
4. Advances the offset and repeats until `offset >= page.total`.

`ManifestStats` is an optional mutable accumulator passed in by
`generate_manifest`.  `generate_manifest_iter` passes `stats=None`, so
counting is skipped in streaming mode.

---

### Adding a new filter operator

1. Add the new key to `FieldFilter` in `_types.py`:

   ```python
   class FieldFilter(TypedDict, total=False):
       ...
       regex_: str   # new operator
   ```

2. Add a matching branch in `_asset_matches` in `_filter.py`:

   ```python
   elif op == "regex_":
       import re
       if not (isinstance(value, str) and re.search(operand, value)):
           return False
   ```

3. Add a test in `tests/utils/test_manifest.py` following the pattern of the
   existing operator tests.

---

### Adding a new fixed row field

Fixed fields are built in `_iter_entries` in `_iterator.py` (the
`dataset_fields` and `yield` dicts).  To add a new field:

1. Add it to the `dataset_fields` dict or the `yield` statement in
   `_iterator.py`.
2. Update the docstring tables in `generate.py` and this README.
3. Add or update the relevant test in `tests/utils/test_manifest.py`.
