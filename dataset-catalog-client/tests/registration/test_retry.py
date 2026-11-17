import datetime
import email.utils

import httpx
import pytest
from pytest_httpx import HTTPXMock

from catalog_client.client.catalog import AsyncCatalogClient, CatalogClient
from catalog_client.exceptions import CatalogConnectionError, CatalogServerError
from catalog_client.registration import retry as retry_module
from catalog_client.registration.retry import RetryPolicy

BASE = "http://test.local"
TOKEN = "test-token"
EDGE_URL = f"{BASE}/api/v1/lineage/edge-1"
LIST_URL = f"{BASE}/api/v1/lineage/"

EDGE_RESPONSE = {
    "id": "edge-1",
    "tombstoned": False,
    "created_at": "2024-01-01T00:00:00Z",
    "last_modified_at": "2024-01-01T00:00:00Z",
    "source_dataset_id": "a",
    "destination_dataset_id": "b",
    "lineage_type": "transformed_from",
}

NO_JITTER = RetryPolicy(max_attempts=4, base_delay=1.0, max_delay=3.0, jitter=False)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []

    async def fake_asleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(retry_module, "_sleep", recorded.append)
    monkeypatch.setattr(retry_module, "_asleep", fake_asleep)
    return recorded


def _client(policy: RetryPolicy | None = NO_JITTER) -> CatalogClient:
    return CatalogClient(base_url=BASE, api_token=TOKEN, retry=policy)


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_get_retries_transient_statuses(
    httpx_mock: HTTPXMock, sleeps: list[float], status: int
) -> None:
    httpx_mock.add_response(url=EDGE_URL, status_code=status, json={"detail": "x"})
    httpx_mock.add_response(url=EDGE_URL, json=EDGE_RESPONSE)
    with _client() as client:
        assert client.lineages.get("edge-1").id == "edge-1"
    assert sleeps == [1.0]


def test_backoff_is_exponential_and_capped(
    httpx_mock: HTTPXMock, sleeps: list[float]
) -> None:
    for _ in range(3):
        httpx_mock.add_response(url=EDGE_URL, status_code=503, json={"detail": "x"})
    httpx_mock.add_response(url=EDGE_URL, json=EDGE_RESPONSE)
    with _client() as client:
        client.lineages.get("edge-1")
    assert sleeps == [1.0, 2.0, 3.0]


def test_gives_up_after_max_attempts(
    httpx_mock: HTTPXMock, sleeps: list[float]
) -> None:
    for _ in range(4):
        httpx_mock.add_response(url=EDGE_URL, status_code=503, json={"detail": "x"})
    with _client() as client:
        with pytest.raises(CatalogServerError):
            client.lineages.get("edge-1")
    assert len(httpx_mock.get_requests()) == 4
    assert len(sleeps) == 3


def test_jitter_stays_within_backoff(
    httpx_mock: HTTPXMock, sleeps: list[float]
) -> None:
    for _ in range(3):
        httpx_mock.add_response(url=EDGE_URL, status_code=503, json={"detail": "x"})
    httpx_mock.add_response(url=EDGE_URL, json=EDGE_RESPONSE)
    policy = RetryPolicy(max_attempts=4, base_delay=1.0, max_delay=3.0)
    with _client(policy) as client:
        client.lineages.get("edge-1")
    assert [0 <= s <= cap for s, cap in zip(sleeps, [1.0, 2.0, 3.0])] == [True] * 3


def test_retry_after_seconds_is_honored_and_capped(
    httpx_mock: HTTPXMock, sleeps: list[float]
) -> None:
    httpx_mock.add_response(url=EDGE_URL, status_code=429, headers={"Retry-After": "2"})
    httpx_mock.add_response(
        url=EDGE_URL, status_code=429, headers={"Retry-After": "120"}
    )
    httpx_mock.add_response(url=EDGE_URL, json=EDGE_RESPONSE)
    with _client() as client:
        client.lineages.get("edge-1")
    assert sleeps == [2.0, 3.0]


def test_retry_after_http_date(httpx_mock: HTTPXMock, sleeps: list[float]) -> None:
    when = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=2)
    httpx_mock.add_response(
        url=EDGE_URL,
        status_code=503,
        headers={"Retry-After": email.utils.format_datetime(when, usegmt=True)},
    )
    httpx_mock.add_response(url=EDGE_URL, json=EDGE_RESPONSE)
    with _client() as client:
        client.lineages.get("edge-1")
    assert 0 < sleeps[0] <= 2.0


def test_get_retries_read_timeout(httpx_mock: HTTPXMock, sleeps: list[float]) -> None:
    httpx_mock.add_exception(httpx.ReadTimeout("slow"), url=EDGE_URL)
    httpx_mock.add_response(url=EDGE_URL, json=EDGE_RESPONSE)
    with _client() as client:
        client.lineages.get("edge-1")
    assert sleeps == [1.0]


def test_post_retries_429(httpx_mock: HTTPXMock, sleeps: list[float]) -> None:
    httpx_mock.add_response(method="POST", url=LIST_URL, status_code=429)
    httpx_mock.add_response(method="POST", url=LIST_URL, json=EDGE_RESPONSE)
    with _client() as client:
        client._http.post("lineage/", json={})
    assert sleeps == [1.0]


def test_post_does_not_retry_503(httpx_mock: HTTPXMock, sleeps: list[float]) -> None:
    httpx_mock.add_response(method="POST", url=LIST_URL, status_code=503)
    with _client() as client:
        assert client._http.post("lineage/", json={}).status_code == 503
    assert sleeps == []


@pytest.mark.parametrize("exc", [httpx.ConnectError("x"), httpx.ConnectTimeout("x")])
def test_post_retries_connect_errors(
    httpx_mock: HTTPXMock, sleeps: list[float], exc: httpx.TransportError
) -> None:
    httpx_mock.add_exception(exc, method="POST", url=LIST_URL)
    httpx_mock.add_response(method="POST", url=LIST_URL, json=EDGE_RESPONSE)
    with _client() as client:
        client._http.post("lineage/", json={})
    assert sleeps == [1.0]


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_non_idempotent_does_not_retry_read_timeout(
    httpx_mock: HTTPXMock, sleeps: list[float], method: str
) -> None:
    httpx_mock.add_exception(httpx.ReadTimeout("slow"), method=method, url=LIST_URL)
    with _client() as client:
        with pytest.raises(httpx.ReadTimeout):
            client._http.request(method, "lineage/", json={})
    assert sleeps == []


def test_no_policy_keeps_single_attempt(
    httpx_mock: HTTPXMock, sleeps: list[float]
) -> None:
    httpx_mock.add_exception(httpx.ConnectError("down"), url=EDGE_URL)
    with _client(None) as client:
        with pytest.raises(CatalogConnectionError):
            client.lineages.get("edge-1")
    assert sleeps == []


def test_retried_request_keeps_auth_header(
    httpx_mock: HTTPXMock, sleeps: list[float]
) -> None:
    httpx_mock.add_response(url=EDGE_URL, status_code=502)
    httpx_mock.add_response(url=EDGE_URL, json=EDGE_RESPONSE)
    with _client() as client:
        client.lineages.get("edge-1")
    assert all(
        r.headers["X-catalog-api-token"] == TOKEN for r in httpx_mock.get_requests()
    )


async def test_async_retries_and_honors_retry_after(
    httpx_mock: HTTPXMock, sleeps: list[float]
) -> None:
    httpx_mock.add_response(url=EDGE_URL, status_code=429, headers={"Retry-After": "1"})
    httpx_mock.add_exception(httpx.ConnectError("x"), url=EDGE_URL)
    httpx_mock.add_response(url=EDGE_URL, json=EDGE_RESPONSE)
    async with AsyncCatalogClient(
        base_url=BASE, api_token=TOKEN, retry=NO_JITTER
    ) as client:
        edge = await client.lineages.get("edge-1")
    assert edge.id == "edge-1"
    assert sleeps == [1.0, 2.0]


async def test_async_post_does_not_retry_502(
    httpx_mock: HTTPXMock, sleeps: list[float]
) -> None:
    httpx_mock.add_response(method="POST", url=LIST_URL, status_code=502)
    async with AsyncCatalogClient(
        base_url=BASE, api_token=TOKEN, retry=NO_JITTER
    ) as client:
        response = await client._http.post("lineage/", json={})
    assert response.status_code == 502
    assert sleeps == []
