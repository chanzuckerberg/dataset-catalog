import json
import sqlite3

import pytest

from catalog_client import CatalogClient

# Core CI intentionally omits native imaging dependencies. The imaging job
# installs the extra on supported Python versions and must run these tests.
icechunk = pytest.importorskip("icechunk", reason="requires catalog-client[imaging]")
zarr = pytest.importorskip("zarr", reason="requires catalog-client[imaging]")
Publisher = pytest.importorskip("catalog_client.publication").Publisher
snapshot_inventory = pytest.importorskip(
    "catalog_client.publication.integrity"
).snapshot_inventory


def candidate(tmp_path):
    repo = icechunk.Repository.create(
        icechunk.local_filesystem_storage(str(tmp_path / "repo"))
    )
    session = repo.writable_session("main")
    zarr.group(session.store).create_array("pixels", shape=(2,), dtype="i4")[:] = [1, 2]
    request = {
        "schema_version": 1,
        "repository_uri": (tmp_path / "repo").as_uri(),
        "source_key": "synthetic:phase0",
        "source_revision": "r1",
        "expected_published_version": 0,
        "expected_snapshot_id": None,
        "idempotency_key": "v1",
        "released_metadata": {
            "name": "Synthetic",
            "modality": "imaging",
            "metadata": {},
            "governance": {},
        },
        "release_notes": "initial",
        "lineage": [],
        "validation_report_ref": "urn:test:validation",
    }
    return repo, session, request


def receipt(request):
    return {
        **request,
        "dataset_id": "server-owned",
        "repository_id": "server-repository",
        "catalog_url": "https://catalog.test/dataset",
        "version": request["expected_published_version"] + 1,
        "status": "AVAILABLE",
    }


def test_pending_recovery_exact_http_snapshot(tmp_path, httpx_mock):
    repo, session, request = candidate(tmp_path)
    httpx_mock.add_response(status_code=503, json={"detail": "unavailable"})
    client = CatalogClient("https://catalog.test", "test-token")
    journal = tmp_path / "publisher.sqlite"
    pending = Publisher(client.publications, journal).commit_and_publish(
        session, request, message="v1", repository=repo
    )
    assert pending["status"] == "PUBLICATION_PENDING"
    snapshot = pending["snapshot_id"]
    before = list(repo.ancestry(branch="main"))

    def success(req):
        import httpx

        payload = json.loads(req.content)
        assert payload["snapshot_id"] == snapshot
        assert req.headers["X-catalog-api-token"] == "test-token"
        return httpx.Response(200, json=receipt(payload))

    httpx_mock.add_callback(success)
    result = Publisher(client.publications, journal).retry("v1", repo)
    assert result["status"] == "AVAILABLE"
    assert len(list(repo.ancestry(branch="main"))) == len(before)
    assert Publisher(client.publications, journal).retry("v1", repo) == result


def test_v1_v2_replay_and_ordinary_commit(tmp_path):
    repo, session, request = candidate(tmp_path)

    class API:
        def __init__(self):
            self.calls = []

        def publish_committed_snapshot(self, payload):
            self.calls.append(payload)
            return receipt(payload)

    api = API()
    publisher = Publisher(api, tmp_path / "state.sqlite")
    one = publisher.commit_and_publish(session, request, message="v1", repository=repo)
    s1 = one["snapshot_id"]
    session = repo.writable_session("main")
    zarr.open_group(session.store)["pixels"][:] = [3, 4]
    request2 = {
        **request,
        "idempotency_key": "v2",
        "source_revision": "r2",
        "expected_published_version": 1,
        "expected_snapshot_id": s1,
    }
    two = publisher.commit_and_publish(session, request2, message="v2", repository=repo)
    assert two["status"] == "AVAILABLE"
    assert two["snapshot_id"] != s1
    assert zarr.open_group(repo.readonly_session(snapshot_id=s1).store, mode="r")[
        "pixels"
    ][:].tolist() == [1, 2]
    assert (
        snapshot_inventory(repo, s1)["manifest_digest"]
        != snapshot_inventory(repo, two["snapshot_id"])["manifest_digest"]
    )
    session = repo.writable_session("main")
    zarr.open_group(session.store).attrs["checkpoint"] = True
    session.commit("ordinary")
    assert len(api.calls) == 2
    with pytest.raises(ValueError, match="Conflicting"):
        publisher.commit_and_publish(
            session,
            {**request, "source_revision": "changed"},
            message="bad",
            repository=repo,
        )


def test_commit_crash_window_recovers_without_commit(tmp_path):
    repo, session, request = candidate(tmp_path)

    class API:
        def publish_committed_snapshot(self, payload):
            return receipt(payload)

    journal = tmp_path / "state.sqlite"
    publisher = Publisher(API(), journal)
    result = publisher.commit_and_publish(
        session, request, message="v1", repository=repo
    )
    # Reproduce disk state immediately after Icechunk commit but before the
    # journal snapshot write. The committed hint must recover this exact ID.
    with sqlite3.connect(journal) as db:
        db.execute("UPDATE publication SET snapshot=NULL,request=NULL,receipt=NULL")
    assert publisher.retry("v1", repo)["snapshot_id"] == result["snapshot_id"]
    assert len(list(repo.ancestry(branch="main"))) == 2


@pytest.mark.parametrize("version", [None, "latest", "1", 0, True])
def test_explicit_consumer_version_required(version):
    with CatalogClient("https://catalog.test", "token") as client:
        with pytest.raises(ValueError):
            client.publications.resolve_release("dataset", version)


def test_repository_uri_mismatch_never_commits(tmp_path):
    repo, session, request = candidate(tmp_path)
    before = repo.lookup_branch("main")
    publisher = Publisher(None, tmp_path / "journal.sqlite")
    request["repository_uri"] = (tmp_path / "missing").as_uri()
    with pytest.raises(Exception):
        publisher.commit_and_publish(session, request, message="bad", repository=repo)
    assert repo.lookup_branch("main") == before


def test_conflict_is_explicit_and_not_retryable(tmp_path, httpx_mock):
    repo, session, request = candidate(tmp_path)
    httpx_mock.add_response(status_code=409, json={"detail": "stale published base"})
    with CatalogClient("https://catalog.test", "token") as client:
        result = Publisher(
            client.publications, tmp_path / "journal.sqlite"
        ).commit_and_publish(session, request, message="v1", repository=repo)
    assert result["status"] == "PUBLICATION_PENDING"
    assert result["snapshot_id"] == repo.lookup_branch("main")
    assert result["http_status"] == 409
    assert result["retryable"] is False
    assert result["action"] == "reconcile_publication_conflict"


def test_incomplete_receipt_never_reports_available(tmp_path, httpx_mock):
    repo, session, request = candidate(tmp_path)
    import httpx

    httpx_mock.add_callback(
        lambda req: httpx.Response(
            200, json={**json.loads(req.content), "version": 1, "status": "AVAILABLE"}
        )
    )
    with CatalogClient("https://catalog.test", "token") as client:
        result = Publisher(
            client.publications, tmp_path / "journal.sqlite"
        ).commit_and_publish(session, request, message="v1", repository=repo)
    assert result["status"] == "PUBLICATION_PENDING"
    assert result["error"] == "ValueError"
