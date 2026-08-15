# Checksum eval

An evaluation harness for `catalog_client.utils.checksum` — digest generation and
size computation.

## Why this exists alongside the unit tests

`tests/utils/checksum/` has ~715 tests and covers the module's behaviour well.
Three questions are structurally outside what it can answer, and each one maps to
a dimension here.

**1. Is the digest right, or just self-consistent?**
The unit suite pins each algorithm to a single published check value
(`CRC64("123456789")`) and otherwise compares our output to our own output. That
proves the polynomial; it says nothing about the streaming/chunking path that
actually produces asset checksums. `conformance` runs every corpus body through
both our machinery and a one-shot implementation that reaches the primitive
directly.

**2. Is it the *same* digest as last release?**
Every invariance and reproducibility test compares our output to our output, so a
change to the Merkle scheme keeps them green while invalidating every checksum
already written into the catalog. `golden` pins digests to vectors committed to
git.

This is not hypothetical. A change confined to the algorithms S3 cannot checksum
itself — combining chunk digests with a position prefix for `blake3`, `blake2b`
and `crc64` — passes **all 715 unit tests** and is caught by `golden` with 66
failures. (The moto-based composite test covers `crc32` and `crc64nvme`, so the
gap is exactly the algorithms S3 has no opinion about.)

**3. Does it hold at production settings?**
`CHUNK_SIZE` is 256MB, and every chunking test shrinks it, so multi-chunk
behaviour at production values has only ever been inferred. And
`hashing.py` claims "peak usage is one `READ_BUFFER` regardless of `CHUNK_SIZE`"
in a comment. `scale` crosses the real boundary and measures peak RSS.

Plus one thing the unit suite tests but only against a mock: **moto is not S3.**
Its own docstring notes it omits `ChecksumType` and writes composites without the
`-N` suffix — the two inputs `_is_composite` exists to handle. `aws_native` runs
that conformance against the real service.

## Running it

```bash
# fast tier: ~1s, <=16MB of temp files, no credentials. Also runs under pytest.
uv run python -m evals.checksum

# full tier: adds the real 256MB chunk boundary, a 768MB body and a 1GB memory
# probe. Minutes, and up to 1GB of temp disk at a time.
uv run python -m evals.checksum --tier full

# real S3. Opt-in only — never implied by the other tiers.
CATALOG_EVAL_S3_BUCKET=my-bucket uv run python -m evals.checksum --tier aws

# one dimension, verbose about skips
uv run python -m evals.checksum --dimension sizes -v
```

Or via make: `make eval`, `make eval-full`, `make eval-aws`, `make eval-golden`.

Exit code is 0 when nothing failed and 1 otherwise. Reports land in
`evals/checksum/reports/<tier>.{json,md}` — JSON for diffing and trending,
markdown for pasting into a PR. `--no-report` prints only.

Tiers gate whole dimensions, not just corpus sizes: `full` implies `fast`, while
`aws` implies nothing, so `--tier aws` reports every other dimension as an
explicit skip rather than running some of it. Each dimension declares the tier it
needs in the registry (`dimensions/__init__.py`) and `run_dimension` enforces it,
so a dimension cannot be registered without stating its cost or run at a tier that
never asked for it. A dimension that yields no checks at all is reported as an
**error** — silence is a harness bug, and "0 checks, all passing" is the one result
an eval must never be able to print.

## Dimensions

| dimension | what it does | tier |
| --- | --- | --- |
| `conformance` | digest, width, `s3_base64` round-trip and router agreement vs one-shot oracles | fast + full |
| `golden` | digests, `merkle_root`, chunk counts and sizes vs committed vectors | fast + full |
| `invariance` | seeded fuzzing: partition-independence, manifest tiling, corruption sensitivity | fast |
| `parallelism` | folder digests are identical at any worker count, across every tree shape | fast |
| `sizes` | `total_size` vs `os.stat`/`os.walk`, plus sparse files, symlinks, hardlinks, unreadable children | fast |
| `scale` | production 256MB chunking, throughput, peak RSS in a child process | full |
| `aws_native` | real-S3 whole-object checksums, `FULL_OBJECT` vs `COMPOSITE`, multipart composites, prefix auto-detection | aws |

## Golden vectors

`evals/checksum/vectors/golden.json` is the anchor. Regenerate only when a digest
change is intended, and treat the diff as the review artifact:

```bash
uv run python -m evals.checksum --update-golden              # fast-tier cases
uv run python -m evals.checksum --tier full --update-golden  # also the 256MB cases
```

Updating merges rather than replaces, so a fast-tier re-pin does not delete the
full-tier vectors only a full run can regenerate.

An unpinned case is not evidence of anything, so it is never a pass. Each one is
reported individually as a **skip** (naming the case), and `golden` then fails
once on `every_case_is_pinned` — without that aggregate verdict, adding or
renaming a corpus case would silently drop its vectors and the run would still
exit 0. The mirror image is `no_orphan_vectors`: because updating merges, a
renamed or deleted case leaves vectors behind that nothing compares. Pruning them
automatically would be wrong — a fast-tier re-pin cannot know the full-tier
cases — so they are reported and deleted by hand.

The config these vectors label `production` cannot silently stop being production:
`corpus.py` binds `CHUNK_SIZE` and `READ_BUFFER` from the library at import rather
than restating them, so there is no second copy to drift. Binding is by value
because `chunking()` patches those attributes for the duration of a check, and a
case's identity must not move with them.

Vectors are recorded per `(case, algorithm, chunk_size, read_buffer)` because
`merkle_root` is partition-dependent by design; small-chunk configurations are
included so multi-chunk composites are pinned without needing a 256MB fixture.

## Corpus

Nothing is committed. Bodies are derived from a case label with **SHAKE128**, a
standardised extendable-output function, so regeneration is byte-identical across
platforms and Python versions — `random.Random` guarantees no such thing, and a
corpus that shifted under an interpreter upgrade would invalidate every pinned
digest at once. Fixtures are deleted as each case finishes, so the disk high-water
mark is one file rather than the whole corpus.

Sizes cluster on the two constants that partition a read: `READ_BUFFER` (64KB)
bounds a single `read()`, `CHUNK_SIZE` (256MB) bounds a manifest entry.

## The AWS tier

Needs `s3:PutObject`, `s3:GetObject`, `s3:HeadObject`, `s3:ListBucket`,
`s3:DeleteObject` and multipart permissions on the target bucket. Safety
properties, since this is the one dimension with outside effects:

- every key is created under `<prefix>/<random run id>/`, so it cannot collide
  with existing data or with a concurrent run
- only keys the run created are deleted, and the count is in the report
- `--keep-s3-objects` leaves them for inspection

It creates roughly 25 small objects plus two ~11MB multipart uploads per run.

## Reproducing a failure

Fuzzed checks carry `seed=` in their message. Replay with `--seed <value>`; the
default seed makes the fast tier deterministic run to run, so CI failures are
reproducible locally.

## Thresholds

`scale` is the only dimension with numeric gates, and they are deliberately
loose — they catch an order-of-magnitude regression, not machine-to-machine
variance:

- `--min-throughput` (default 20 MB/s)
- `--max-peak-rss-mb` (default 96) — RSS growth above the child process's own
  baseline. The stated invariant is 64KB; 96MB leaves room for allocator slack
  and extension modules while still failing loudly if a 256MB chunk is ever
  buffered.

## Adding a dimension

Create `evals/checksum/dimensions/<name>.py` exposing `NAME` and
`run(ctx) -> Iterator[Check]`, then add a `Dimension(...)` for it in
`dimensions/__init__.py` with the cheapest tier it can run at. `run()` does not
check the tier itself — `run_dimension` does that from the registry, so the guard
cannot be forgotten.

Yield checks, never assert: a dimension that raises loses every result after the
failure, which is the opposite of what an eval is for. Build checks with
`compare()` / `assert_that()` / `skip()` from `harness.py`, and tag each with the
tier it can afford to run at.

If the fast tier includes the new dimension, add its name to `expected_to_run` in
`tests/test_checksum_eval.py`. That set is written out rather than derived from the
registry on purpose: deriving it would make the test blind to a `needs` tier set
too high, since the expectation would move along with the mistake.
