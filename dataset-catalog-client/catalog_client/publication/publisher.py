"""Producer-owned durable commit/publication recovery. Never allocates releases."""

import fcntl
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
import icechunk

from catalog_client.client.publications import PublicationClient
from catalog_client.publication.integrity import canonical_json, snapshot_inventory


def _open_publication_repository(uri: str) -> icechunk.Repository:
    parts = urlsplit(uri)
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError(
            "Repository URI must not contain credentials, query or fragment"
        )
    if parts.scheme == "file" and not parts.netloc and parts.path.startswith("/"):
        storage = icechunk.local_filesystem_storage(unquote(parts.path))
    elif parts.scheme == "s3" and parts.netloc:
        storage = icechunk.s3_storage(
            bucket=parts.netloc, prefix=parts.path.lstrip("/"), from_env=True
        )
    else:
        raise ValueError("An absolute local file URI or s3 URI is required")
    return icechunk.Repository.open(storage)


class Publisher:
    """Explicit publication with a SQLite journal on durable local POSIX storage.

    The journal and its lock must be shared by workers publishing a repository.
    Keep the journal and referenced snapshots until all pending work is resolved.
    A process lock fences writers for the entire operation; SQLite FULL commits
    persist intent before Icechunk commit. No retries re-commit a session.
    """

    def __init__(self, publications: PublicationClient, state_path: str | Path):
        self.publications = publications
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS publication (key TEXT PRIMARY KEY, intent TEXT NOT NULL, branch TEXT NOT NULL, snapshot TEXT, request TEXT, receipt TEXT)"
            )
            db.commit()

    @contextmanager
    def _locked(self):
        with open(str(self.state_path) + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with sqlite3.connect(self.state_path) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA synchronous=FULL")
                yield db

    def commit_and_publish(
        self,
        session: icechunk.Session,
        request: dict,
        *,
        message: str,
        repository: icechunk.Repository,
    ) -> dict:
        """Commit once, then publish; repeat calls recover the persisted intent."""
        request = json.loads(canonical_json(request))
        request["repository_uri"] = request["repository_uri"].rstrip("/")
        if {"snapshot_id", "manifest_digest"} & request.keys():
            raise ValueError("The wrapper computes snapshot_id and manifest_digest")
        key = request["idempotency_key"]
        if not isinstance(key, str) or not key:
            raise ValueError("A nonempty idempotency_key is required")
        intent = canonical_json(request)
        with self._locked() as db:
            row = db.execute("SELECT * FROM publication WHERE key=?", (key,)).fetchone()
            if row:
                if row["intent"] != intent:
                    raise ValueError("Conflicting reuse of producer idempotency key")
                return self._retry(db, row, repository)
            if not session.branch:
                raise ValueError("Publication requires a writable named branch")
            advertised = _open_publication_repository(request["repository_uri"])
            if advertised.lookup_branch(session.branch) != session.snapshot_id:
                raise ValueError(
                    "Advertised repository does not contain the session branch base"
                )
            expected = request["expected_snapshot_id"]
            if expected is not None and session.snapshot_id != expected:
                raise ValueError(
                    "Session does not start at the expected published snapshot"
                )
            if repository.lookup_branch(session.branch) != session.snapshot_id:
                raise ValueError("Session branch base is stale")
            db.execute(
                "INSERT INTO publication(key,intent,branch) VALUES(?,?,?)",
                (key, intent, session.branch),
            )
            db.commit()
            hint = {
                "schema_version": 1,
                "idempotency_key": key,
                "intent_sha256": hashlib.sha256(intent.encode()).hexdigest(),
            }
            # No automatic rebase: the producer must reconcile a losing writer.
            snapshot = session.commit(message, metadata={"catalog_publication": hint})
            try:
                db.execute(
                    "UPDATE publication SET snapshot=? WHERE key=?", (snapshot, key)
                )
                db.commit()
            except sqlite3.Error:
                return {
                    "status": "PUBLICATION_PENDING",
                    "snapshot_id": snapshot,
                    "idempotency_key": key,
                    "error": "JournalWriteError",
                    "retryable": True,
                }
            row = db.execute("SELECT * FROM publication WHERE key=?", (key,)).fetchone()
            return self._retry(db, row, repository)

    def retry(self, key: str, repository: icechunk.Repository) -> dict:
        """Recover an existing intent. This method never writes or commits data."""
        with self._locked() as db:
            row = db.execute("SELECT * FROM publication WHERE key=?", (key,)).fetchone()
            if row is None:
                raise KeyError(key)
            return self._retry(db, row, repository)

    def _retry(
        self, db: sqlite3.Connection, row: sqlite3.Row, repository: icechunk.Repository
    ) -> dict:
        key = row["key"]
        snapshot = row["snapshot"]
        if snapshot is None:
            hint = {
                "schema_version": 1,
                "idempotency_key": key,
                "intent_sha256": hashlib.sha256(row["intent"].encode()).hexdigest(),
            }
            matches = [
                s.id
                for s in repository.ancestry(branch=row["branch"])
                if s.metadata.get("catalog_publication") == hint
            ]
            if len(matches) != 1:
                raise RuntimeError(
                    "Commit outcome unresolved: retain journal and inspect branch history; never recommit this key"
                )
            snapshot = matches[0]
            db.execute("UPDATE publication SET snapshot=? WHERE key=?", (snapshot, key))
            db.commit()
        result = {"snapshot_id": snapshot, "idempotency_key": key}
        if row["receipt"]:
            return {
                **result,
                "status": "AVAILABLE",
                "release": json.loads(row["receipt"]),
            }
        try:
            advertised = _open_publication_repository(
                json.loads(row["intent"])["repository_uri"]
            )
            evidence = snapshot_inventory(advertised, snapshot)
            if row["request"]:
                request = json.loads(row["request"])
                if evidence["manifest_digest"] != request["manifest_digest"]:
                    raise ValueError(
                        "Published repository snapshot failed integrity check"
                    )
            else:
                if evidence != snapshot_inventory(repository, snapshot):
                    raise ValueError(
                        "Advertised repository does not match the committed repository"
                    )
                request = {
                    **json.loads(row["intent"]),
                    "snapshot_id": snapshot,
                    "manifest_digest": evidence["manifest_digest"],
                }
                db.execute(
                    "UPDATE publication SET request=? WHERE key=?",
                    (canonical_json(request), key),
                )
                db.commit()
            release = self.publications.publish_committed_snapshot(request)
            if any(
                not isinstance(release.get(name), str) or not release[name]
                for name in ("dataset_id", "repository_id", "catalog_url")
            ):
                raise ValueError("Catalog receipt lacks required identity fields")
            for name in (
                "snapshot_id",
                "repository_uri",
                "manifest_digest",
                "source_key",
                "source_revision",
            ):
                if release[name] != request[name]:
                    raise ValueError(f"Catalog receipt mismatches {name}")
            if (
                release["status"] != "AVAILABLE"
                or type(release["version"]) is not int
                or release["version"] != request["expected_published_version"] + 1
            ):
                raise ValueError("Invalid Catalog release receipt")
            db.execute(
                "UPDATE publication SET receipt=? WHERE key=?",
                (canonical_json(release), key),
            )
            db.commit()
            return {**result, "status": "AVAILABLE", "release": release}
        except Exception as exc:
            # Once committed, all publication/verification failures retain the
            # same snapshot. Expose the failure class, without token-bearing URLs.
            status_code = (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError)
                else getattr(exc, "status_code", None)
            )
            return {
                **result,
                "status": "PUBLICATION_PENDING",
                "error": type(exc).__name__,
                "http_status": status_code,
                "retryable": status_code is None
                or status_code >= 500
                or status_code in (408, 429),
                "action": "reconcile_publication_conflict"
                if status_code == 409
                else "inspect_error_before_retry",
            }
