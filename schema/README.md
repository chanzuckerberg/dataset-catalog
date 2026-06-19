# Dataset Catalog Schema

The authoritative, field-level definition of the Scientific Dataset Catalog: its four
core entities (Data Asset, Dataset, Collection, Lineage Edge), the fields each carries,
and how records behave when they are updated.

This directory documents the schema only. For how to *use* the catalog from the Python
client, see [`dataset-catalog-client/USAGE.md`](../dataset-catalog-client/USAGE.md).

## Versions

| Version | Document | Status |
|---------|----------|--------|
| v1.4.0 | [`v1.4.0/schema.md`](v1.4.0/schema.md) | **Current** — default for new registrations |

The active schema version is recorded on each dataset record as `record_schema_version`.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for the full version history and migration notes.
