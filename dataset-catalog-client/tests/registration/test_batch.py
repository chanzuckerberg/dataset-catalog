import logging
import threading
import time
from collections.abc import Iterator

import pydantic
import pytest

from catalog_client.exceptions import NotFoundError
from catalog_client.registration.batch import BatchReport, run_batch


def test_all_succeed() -> None:
    report = run_batch(["a", "b", "c"], lambda item: f"id-{item}")
    assert sorted(report.succeeded) == [("a", "id-a"), ("b", "id-b"), ("c", "id-c")]
    assert report.failed == []
    assert report.summary() == "3 registered, 0 failed"
    assert report.exit_code == 0


def test_failure_is_isolated_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    def handle(item: str) -> str:
        if item == "b":
            raise NotFoundError(404, "No dataset found")
        return f"id-{item}"

    with caplog.at_level(logging.ERROR):
        report = run_batch(["a", "b", "c"], handle)

    assert sorted(k for k, _ in report.succeeded) == ["a", "c"]
    assert report.failed == [("b", "NotFoundError: HTTP 404: No dataset found")]
    assert report.exit_code == 1
    assert [r.getMessage() for r in caplog.records] == [
        "b failed: NotFoundError: HTTP 404: No dataset found"
    ]
    assert all(r.exc_info is None for r in caplog.records)


def test_summary_lists_failures() -> None:
    report = BatchReport(
        succeeded=[("x", "1")],
        failed=[("key-a", "NotFoundError: gone"), ("key-b", "ValueError: bad")],
    )
    assert report.summary() == (
        "1 registered, 2 failed: key-a (NotFoundError: gone), key-b (ValueError: bad)"
    )


def test_summary_verb_for_dry_runs() -> None:
    report = BatchReport(succeeded=[("x", "1")], failed=[])
    assert report.summary("planned") == "1 planned, 0 failed"


def test_pydantic_errors_keep_only_path_and_message() -> None:
    class Governance(pydantic.BaseModel):
        is_pii: bool
        data_steward: str

    def handle(item: str) -> str:
        Governance.model_validate({"is_pii": None})
        return item

    report = run_batch(["a"], handle)
    assert report.failed == [
        (
            "a",
            "ValidationError (Governance): is_pii: Input should be a valid boolean; "
            "data_steward: Field required",
        )
    ]


def test_multiline_messages_collapse_to_one_line() -> None:
    def handle(item: str) -> str:
        raise ValueError("first\n  second")

    report = run_batch(["a"], handle)
    assert report.failed == [("a", "ValueError: first second")]


def test_custom_key_and_logger(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("pipeline")

    def handle(item: dict[str, str]) -> str:
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR, logger="pipeline"):
        report = run_batch(
            [{"name": "s1"}], handle, key=lambda item: item["name"], logger=logger
        )

    assert report.failed == [("s1", "RuntimeError: boom")]
    assert caplog.records[0].name == "pipeline"


def test_failing_key_is_recorded_and_batch_continues() -> None:
    def key(item: int) -> str:
        if item == 0:
            raise KeyError("name")
        return str(item)

    report = run_batch([0, 1], lambda item: "ok", key=key)
    assert report.failed == [("item[0]", "KeyError: 'name'")]
    assert report.succeeded == [("1", "ok")]


def test_concurrency_is_capped() -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def handle(item: int) -> str:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return str(item)

    report = run_batch(range(20), handle, max_workers=3)
    assert len(report.succeeded) == 20
    assert peak <= 3


def test_items_are_consumed_lazily() -> None:
    pulled = 0
    pulled_while_blocked: list[int] = []
    release = threading.Event()

    def items() -> Iterator[int]:
        nonlocal pulled
        for i in range(1000):
            pulled += 1
            yield i

    def handle(item: int) -> str:
        release.wait(timeout=5)
        return str(item)

    def observe_then_release() -> None:
        time.sleep(0.1)
        pulled_while_blocked.append(pulled)
        release.set()

    watcher = threading.Thread(target=observe_then_release)
    watcher.start()
    report = run_batch(items(), handle, max_workers=2)
    watcher.join()
    # Every worker is stuck, so only the in-flight window (2 x max_workers) was read.
    assert pulled_while_blocked == [4]
    assert len(report.succeeded) == 1000


def test_base_exception_aborts_batch() -> None:
    def handle(item: int) -> str:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_batch([1, 2, 3], handle, max_workers=1)
