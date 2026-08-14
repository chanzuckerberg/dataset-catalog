"""Command-line entry point for the checksum eval."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

from evals.checksum import report
from evals.checksum.dimensions import DESCRIPTIONS, DIMENSIONS
from evals.checksum.harness import Context, Thresholds, Tier, run_dimension

DEFAULT_REPORT_DIR = Path(__file__).resolve().parent / "reports"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m evals.checksum",
        description="Evaluate checksum generation and size computation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="dimensions:\n"
        + "\n".join(f"  {name:<12} {DESCRIPTIONS[name]}" for name in DIMENSIONS),
    )
    parser.add_argument(
        "--tier",
        type=Tier,
        choices=list(Tier),
        default=Tier.fast,
        help="fast (CI-safe, default) · full (adds 256MB/1GB cases) · "
        "aws (real S3 only, never implied by the others)",
    )
    parser.add_argument(
        "--dimension",
        action="append",
        choices=list(DIMENSIONS),
        dest="dimensions",
        help="run only this dimension (repeatable); default is all of them",
    )
    parser.add_argument(
        "--seed",
        default="catalog-checksum-eval",
        help="seed for the fuzzed dimensions; reported with every check so a "
        "failure is replayable",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help=f"where to write <tier>.json and <tier>.md (default {DEFAULT_REPORT_DIR})",
    )
    parser.add_argument(
        "--no-report", action="store_true", help="print results without writing files"
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        help="directory for generated fixtures (default: a temp dir, removed after)",
    )
    parser.add_argument(
        "--update-golden",
        action="store_true",
        help="re-pin the golden vectors from this run instead of comparing "
        "against them, then review the diff",
    )
    parser.add_argument(
        "--s3-bucket",
        default=os.environ.get("CATALOG_EVAL_S3_BUCKET"),
        help="bucket for the aws tier (default: $CATALOG_EVAL_S3_BUCKET)",
    )
    parser.add_argument(
        "--s3-prefix",
        default="catalog-checksum-eval",
        help="key prefix for objects the aws tier creates",
    )
    parser.add_argument(
        "--keep-s3-objects",
        action="store_true",
        help="do not delete the objects the aws tier created",
    )
    parser.add_argument(
        "--fuzz-cases",
        type=int,
        default=Thresholds.fuzz_cases,
        help="how many randomised invariance cases to draw",
    )
    parser.add_argument(
        "--min-throughput",
        type=float,
        default=Thresholds.min_throughput_mb_s,
        help="MB/s floor for the scale dimension",
    )
    parser.add_argument(
        "--max-peak-rss-mb",
        type=float,
        default=Thresholds.max_peak_rss_bytes / (1024 * 1024),
        help="ceiling on RSS growth while hashing, in MB",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="also list skips")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    owns_workdir = args.workdir is None
    workdir = (
        Path(tempfile.mkdtemp(prefix="checksum-eval-"))
        if owns_workdir
        else args.workdir
    )
    workdir.mkdir(parents=True, exist_ok=True)

    ctx = Context(
        tier=args.tier,
        workdir=workdir,
        seed=args.seed,
        update_golden=args.update_golden,
        s3_bucket=args.s3_bucket,
        s3_prefix=args.s3_prefix,
        keep_s3_objects=args.keep_s3_objects,
        thresholds=Thresholds(
            min_throughput_mb_s=args.min_throughput,
            max_peak_rss_bytes=int(args.max_peak_rss_mb * 1024 * 1024),
            fuzz_cases=args.fuzz_cases,
        ),
    )

    selected = args.dimensions or list(DIMENSIONS)
    print(f"checksum eval · tier={args.tier.value} · seed={args.seed}", file=sys.stderr)
    print(f"fixtures in {workdir}", file=sys.stderr)

    try:
        runs = []
        for name in selected:
            print(f"  running {name}…", file=sys.stderr, flush=True)
            runs.append(run_dimension(name, DIMENSIONS[name], ctx))
    finally:
        if owns_workdir:
            shutil.rmtree(workdir, ignore_errors=True)

    payload = report.build(ctx, runs)
    print()
    print(report.console(payload, verbose=args.verbose))

    if not args.no_report:
        json_path, markdown_path = report.write(payload, args.report_dir)
        print(f"\nreports: {json_path}\n         {markdown_path}")

    # --update-golden rewrites the vectors, so its run has nothing to compare
    # against; exiting non-zero there would just be noise in a re-pin.
    if args.update_golden:
        return 0
    return 0 if payload["summary"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
