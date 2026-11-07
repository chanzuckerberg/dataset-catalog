---
name: field-reference
description: Looks up catalog record fields — type, whether required, allowed values, meaning, who decides the value, examples by data type (imaging, sequencing, mass spec), and common mistakes — for datasets, assets (locations), collections, and lineage edges. Use when asked "what is <field>?", "what values can <field> take?", "is <field> required?", or "which field holds <thing>?".
argument-hint: "<field name or question>"
context: fork
model: haiku
---

# Field reference

Answer field questions from the generated reference in this skill, never from memory. If invoked
with a question, answer it: $ARGUMENTS

## Where fields live

| Record | Human-readable | Root model |
|---|---|---|
| Dataset (top level, `governance.*`, `metadata.*`, `data_quality.*`) | `${CLAUDE_PLUGIN_ROOT}/skills/field-reference/fields/dataset.md` | `DatasetRequest` |
| Asset, i.e. each entry of a dataset's `locations` | `${CLAUDE_PLUGIN_ROOT}/skills/field-reference/fields/asset.md` | `DataAssetRequest` |
| Collection | `${CLAUDE_PLUGIN_ROOT}/skills/field-reference/fields/collection.md` | `CollectionRequest` |
| Lineage edge | `${CLAUDE_PLUGIN_ROOT}/skills/field-reference/fields/lineage.md` | `LineageEdgeRequest` |

`${CLAUDE_PLUGIN_ROOT}/skills/field-reference/fields.json` holds the same data for code; the
validator (`scripts/validate_record.py`) reads it.

## How to look a field up

1. Pick the file from the table. Each field is a `### <dotted.path>` heading; list items use `[]`
   (e.g. `metadata.sample.organism[].ontology_id`). Grep for the heading rather than reading the
   whole file: `grep -n -A12 '^### governance.is_pii$' .../fields/dataset.md`.
2. Quote the entry's lines that answer the question: Type, Required, allowed values, Meaning,
   Decided by, Examples, Common mistakes. Cite the file and heading.
3. A field that is not in the files does not exist. Say so, and name the closest real field. Do not
   invent one: a misspelt key in a block that accepts extra keys is stored silently, and at the
   top level of a record it is dropped.
4. **Source** tells you how to send it: `client + API` through the client; **API-only** over REST
   until the client catches up; **client-only** means the API drops it.

"Required: yes (when `X` is present)" means required inside `X`; whether `X` itself is required is
on `X`'s own entry.

## Is the reference stale?

The first lines of each file say which `catalog-client` version and API spec generated it. If the
installed client is newer (the plugin's session-start check warns about this), fields added since
are missing here. Then either regenerate, with the Python that has `catalog_client` installed:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/field-reference/scripts/generate.py"   # reads CATALOG_API_TOKEN for the spec
```

or, without regenerating, read the installed models directly and say the reference is behind:
`python -c "from catalog_client import DatasetRequest; import json; print(json.dumps(DatasetRequest.model_json_schema(), indent=1))"`.

Only `examples.json` is hand-edited; everything else is generated, so fix wording there and rerun.

## Scope

Definitions only. How to choose a value, compute it, or run a registration: `registration-script`.
What a dataset, collection, or lineage edge is: `concepts`.
