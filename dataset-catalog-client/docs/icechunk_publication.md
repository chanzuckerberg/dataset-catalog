# Explicit Icechunk publication (Phase 0)

Install `catalog-client[imaging]`. This optional module uses native Icechunk 2.x,
Zarr 3.x, and a durable local POSIX SQLite journal. It does not change ordinary
Icechunk `session.commit()` behavior. Only an explicit publication call creates
a Catalog release.

```python
from catalog_client import CatalogClient
from catalog_client.publication import Publisher

with CatalogClient(base_url=catalog_url, api_token=token) as client:
    publisher = Publisher(client.publications, "/durable/publisher/state.sqlite")
    result = publisher.commit_and_publish(
        session, request, message="Approved correction", repository=repository
    )
```

`request` follows Catalog schema version 1, excluding `snapshot_id` and
`manifest_digest`, which the wrapper computes. The request includes repository
URI, stable source key and revision, expected published version and snapshot,
idempotency key, released metadata, lineage, release notes, and validation report
reference. Catalog administrators must configure an exact source grant for the
authenticated producer and repository before first publication. The wrapper
never assigns a dataset ID or released version.

For the first release, use `expected_published_version=0` and
`expected_snapshot_id=None`. For a correction, call
`client.publications.resolve_repository(repository_uri=...)` and open its
`latest_snapshot_id` as the producer base. Pass the returned version and snapshot
as expectations. A stale base fails explicitly; there is no automatic rebase.
The scientific approval and source-fidelity checks remain with the producer.

## Recovery

The journal persists intent before commit, and the commit includes a
`catalog_publication` recovery hint. After commit, the wrapper saves the snapshot
ID, reads every logical key to compute the digest, and publishes that exact
snapshot. Catalog network errors, rejected requests, and verification errors
return `PUBLICATION_PENDING` with the snapshot ID, key, and error class. The
complete request stays in the journal; no token is saved there.

```python
result = publisher.retry(idempotency_key, repository)
```

Retry never rewrites or recommits. If a process dies between commit and journal
update, retry searches the recorded branch history for the matching intent hint.
If it cannot find exactly one match, it fails for operator inspection rather
than guessing whether commit succeeded. Keep the journal and branch history.
Do not reset branches or garbage-collect pending or Catalog-bound snapshots.
An unresolved pre-commit failure needs an explicit new intent after an operator
establishes that no commit occurred.

All publishers of one local repository must use the same journal and POSIX lock.
The lock serializes this wrapper's local operations. It does not fence unrelated
Icechunk writers. Use storage with Icechunk's required conditional-write support
for independent concurrent publishers. This local adapter is not a distributed
workflow store and is not intended for NFS SQLite locking.

## Verification and consumer selection

`snapshot_inventory(repository, snapshot_id)` reads every logical store key at
the exact readonly snapshot and rejects virtual references. It hashes canonical
JSON of sorted `{key,size,sha256}` entries (ASCII escaping, sorted object keys,
compact separators). The result is `icechunk-logical-sha256-v1` with a
`sha256:<hex>` manifest digest, key count, and byte count. Hermes compares this
same digest after localization. This proves logical object availability; it is
not a physical-object closure manifest or a garbage-collection policy.

This full-read verifier is for bounded Phase 0 fixtures. Production-sized runs
need a budgeted streaming verification and retention design.

Consumers call `client.publications.resolve_release(dataset_id, version)`.
The version must be an explicit positive integer. The returned source URI is
not permission to silently train from remote storage; training must consume a
verified local replica matching the exact release.

## Producer adoption

OPS should call the wrapper after its selected Nextflow/acquisition validation
gate, using a durable workflow-owned journal. BioCurator should use the same
wrapper after source freeze, DCA checks, and native Icechunk conversion. Both
must keep source identity and release approval stable across retries. Neither
integration should assign Catalog versions or run registration on every ordinary
checkpoint. Their deployment and retention configuration remain component-owner
work; these examples do not establish live adoption.

Run `pytest tests/test_publication.py -q` for native v1/v2 replay, ordinary
commit separation, durable failed-registration retry, and crash-window recovery.
The HTTP test substitutes Catalog responses; server integration evidence is
reported separately.
