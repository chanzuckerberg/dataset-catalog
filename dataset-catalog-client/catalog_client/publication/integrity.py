"""Bounded Phase 0 verification of all native logical snapshot objects."""

import asyncio
import hashlib
import json

import icechunk
from zarr.core.buffer import default_buffer_prototype


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


async def _inventory(repository: icechunk.Repository, snapshot_id: str) -> dict:
    session = repository.readonly_session(snapshot_id=snapshot_id)
    if next(iter(session.all_virtual_chunk_locations()), None) is not None:
        raise ValueError("Phase 0 requires native chunks, not virtual references")
    store = session.store
    keys = sorted([key async for key in store.list()])
    entries = []
    for key in keys:
        value = await store.get(key, prototype=default_buffer_prototype())
        if value is None:
            raise ValueError(f"Snapshot object is missing: {key}")
        data = value.to_bytes()
        entries.append(
            {"key": key, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        )
    if not entries:
        raise ValueError("Cannot release an empty snapshot")
    return {
        "algorithm": "icechunk-logical-sha256-v1",
        "manifest_digest": "sha256:"
        + hashlib.sha256(canonical_json(entries).encode()).hexdigest(),
        "key_count": len(entries),
        "byte_count": sum(entry["size"] for entry in entries),
    }


def snapshot_inventory(repository: icechunk.Repository, snapshot_id: str) -> dict:
    """Read every logical key at an exact snapshot and hash its bytes.

    This synchronous, full-read verifier is intended for bounded Phase 0 data.
    It proves logical object availability, not physical repository closure or
    retention. Missing physical chunks raise during reads. Do not run it on a
    training-sized repository without an explicit transfer and verification budget.
    """
    return asyncio.run(_inventory(repository, snapshot_id))
