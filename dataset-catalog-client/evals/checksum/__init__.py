"""
Evaluation harness for checksum generation and size computation.

The unit suite in tests/utils/checksum/ answers "does the code do what it says".
This harness answers three questions it structurally cannot:

  Is the digest right?      Compared against independent one-shot
                            implementations, not against our own output.
  Is it the same digest?    Compared against golden vectors committed to git, so
                            a change that would invalidate every checksum
                            already in the catalog shows up as a file diff.
  Does it hold at scale?    Measured at the real 256MB CHUNK_SIZE, with
                            throughput and peak RSS recorded rather than assumed.

Run it:

    python -m evals.checksum                       # fast tier, CI-safe
    python -m evals.checksum --tier full           # adds 256MB/1GB cases
    CATALOG_EVAL_S3_BUCKET=b python -m evals.checksum --tier aws
    python -m evals.checksum --update-golden       # re-pin vectors, review diff

See evals/README.md.
"""

from evals.checksum.harness import Check, Context, Status, Thresholds, Tier

__all__ = ["Check", "Context", "Status", "Thresholds", "Tier"]
