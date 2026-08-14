"""
Turning checks into a report.

Two artifacts per run: a JSON file meant for machines (diffing runs, trending
throughput) and a markdown file meant for a pull request. Both carry the
environment, because a throughput number or a skipped algorithm is not
interpretable without knowing which install produced it.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from evals.checksum.corpus import CHUNK_SIZE, READ_BUFFER
from evals.checksum.harness import Check, Context, DimensionRun, Status

_STATUS_MARK = {
    Status.passed: "pass",
    Status.failed: "FAIL",
    Status.skipped: "skip",
    Status.errored: "ERROR",
}

_STATUS_FIELD = {
    Status.passed: "passed",
    Status.failed: "failed",
    Status.skipped: "skipped",
    Status.errored: "errored",
}


@dataclass
class Summary:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errored: int = 0

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped + self.errored

    @property
    def ran(self) -> int:
        """Checks that produced a verdict. Skips are not evidence either way."""
        return self.passed + self.failed + self.errored

    @property
    def pass_rate(self) -> float:
        return self.passed / self.ran if self.ran else 0.0

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.errored == 0

    def add(self, check: Check) -> None:
        field = _STATUS_FIELD[check.status]
        setattr(self, field, getattr(self, field) + 1)

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errored": self.errored,
            "pass_rate": round(self.pass_rate, 4),
            "ok": self.ok,
        }


def _first_line(message: str) -> str:
    """
    The first line of a check's message, or a placeholder if there is none.

    `splitlines()[0]` would raise on an empty message, which `assert_that` allows
    a caller to pass. Report generation runs after the checks, so an IndexError
    here would throw away a whole run's results — including the failure that
    triggered it.
    """
    lines = message.splitlines()
    return lines[0] if lines else "(no message)"


def summarise(checks: list[Check]) -> Summary:
    summary = Summary()
    for check in checks:
        summary.add(check)
    return summary


def environment(ctx: Context) -> dict:
    from catalog_client.utils.checksum.algorithm import Algorithm, default_algorithm
    from evals.checksum.harness import available_algorithms

    usable = available_algorithms()
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "algorithms_available": [a.value for a in usable],
        "algorithms_missing": [a.value for a in Algorithm if a not in usable],
        "default_algorithm": default_algorithm().value,
        "chunk_size": CHUNK_SIZE,
        "read_buffer": READ_BUFFER,
        "tier": ctx.tier.value,
        "seed": ctx.seed,
        "thresholds": {
            "min_throughput_mb_s": ctx.thresholds.min_throughput_mb_s,
            "max_peak_rss_bytes": ctx.thresholds.max_peak_rss_bytes,
            "fuzz_cases": ctx.thresholds.fuzz_cases,
        },
    }


def build(ctx: Context, runs: list[DimensionRun]) -> dict:
    all_checks = [check for run in runs for check in run.checks]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": environment(ctx),
        "summary": summarise(all_checks).as_dict(),
        "dimensions": [
            {
                "name": run.name,
                "seconds": round(run.seconds, 2),
                "summary": summarise(run.checks).as_dict(),
                "checks": [
                    {
                        "id": check.id,
                        "tier": check.tier.value,
                        "status": check.status.value,
                        "message": check.message,
                        "metrics": check.metrics,
                    }
                    for check in run.checks
                ],
            }
            for run in runs
        ],
    }


def markdown(payload: dict) -> str:
    summary = payload["summary"]
    env = payload["environment"]
    verdict = "PASS" if summary["ok"] else "FAIL"
    lines = [
        f"# Checksum eval — {verdict}",
        "",
        f"- tier: `{env['tier']}` · seed: `{env['seed']}`",
        f"- {summary['passed']} passed, {summary['failed']} failed, "
        f"{summary['errored']} errored, {summary['skipped']} skipped "
        f"({summary['pass_rate'] * 100:.1f}% of verdicts passing)",
        f"- python {env['python']} on {env['platform']}",
        f"- algorithms: {', '.join(env['algorithms_available']) or 'none'}"
        + (
            f" (missing: {', '.join(env['algorithms_missing'])})"
            if env["algorithms_missing"]
            else ""
        ),
        f"- constants: CHUNK_SIZE={env['chunk_size']} READ_BUFFER={env['read_buffer']}",
        f"- generated: {payload['generated_at']}",
        "",
        "| dimension | pass | fail | error | skip | seconds |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for dimension in payload["dimensions"]:
        counts = dimension["summary"]
        lines.append(
            f"| {dimension['name']} | {counts['passed']} | {counts['failed']} "
            f"| {counts['errored']} | {counts['skipped']} | {dimension['seconds']} |"
        )

    problems = [
        check
        for dimension in payload["dimensions"]
        for check in dimension["checks"]
        if check["status"] in ("fail", "error")
    ]
    if problems:
        lines += ["", "## Failures", ""]
        for check in problems:
            lines.append(f"- **{check['id']}** — {_first_line(check['message'])}")

    measured = [
        (check["id"], check["metrics"])
        for dimension in payload["dimensions"]
        for check in dimension["checks"]
        if "throughput_mb_s" in check["metrics"] or "peak_rss_mb" in check["metrics"]
    ]
    if measured:
        lines += ["", "## Measurements", "", "| check | metrics |", "| --- | --- |"]
        for check_id, metrics in measured:
            rendered = ", ".join(f"{k}={v}" for k, v in sorted(metrics.items()))
            lines.append(f"| {check_id} | {rendered} |")

    return "\n".join(lines) + "\n"


def write(payload: dict, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    tier = payload["environment"]["tier"]
    json_path = directory / f"{tier}.json"
    markdown_path = directory / f"{tier}.md"
    with open(json_path, "w") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    markdown_path.write_text(markdown(payload))
    return json_path, markdown_path


def console(payload: dict, verbose: bool = False) -> str:
    """A compact terminal summary. Failures are always shown in full."""
    lines = []
    for dimension in payload["dimensions"]:
        counts = dimension["summary"]
        state = "ok " if counts["ok"] else "BAD"
        lines.append(
            f"[{state}] {dimension['name']:<12} "
            f"{counts['passed']:>4} pass  {counts['failed']:>3} fail  "
            f"{counts['errored']:>2} err  {counts['skipped']:>3} skip  "
            f"{dimension['seconds']:>7.2f}s"
        )
        for check in dimension["checks"]:
            if check["status"] in ("fail", "error"):
                lines.append(
                    f"        {_STATUS_MARK[Status(check['status'])]} {check['id']}"
                )
                for line in check["message"].splitlines()[:4]:
                    lines.append(f"             {line}")
            elif verbose and check["status"] == "skip" and check["message"]:
                lines.append(f"        skip {check['id']}: {check['message']}")

    summary = payload["summary"]
    lines.append("")
    lines.append(
        f"{'PASS' if summary['ok'] else 'FAIL'}: {summary['passed']} passed, "
        f"{summary['failed']} failed, {summary['errored']} errored, "
        f"{summary['skipped']} skipped"
    )
    return "\n".join(lines)
