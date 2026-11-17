# Registration Runtime

Building blocks for registration scripts that run unattended in a pipeline:
re-runnable `register()`, a read-only dry run, retries with backoff, a batch
runner that isolates failures, a startup compatibility check, and local
validation from the shell.

Everything here is importable from `catalog_client.registration` and from the
top-level `catalog_client` package.

---

## User guide

### A pipeline script, end to end

```python
import logging
import os
import sys

from catalog_client import (
    CatalogClient,
    RetryPolicy,
    check_compatibility,
    run_batch,
)

logging.basicConfig(level=logging.INFO)
DRY_RUN = os.environ.get("DRY_RUN") == "1"

with CatalogClient(
    base_url=os.environ["CATALOG_API_URL"],
    api_token=os.environ["CATALOG_API_TOKEN"],
    retry=RetryPolicy(),
) as client:
    check_compatibility(client)  # fail at startup, not on record 4,000

    def handle(sample) -> str:
        request = build_request(sample)  # your mapping -> RegistrationRequest
        if DRY_RUN:
            plan = client.plan(request, update_if_exists=True, error_on_duplicate=False)
            logging.info("%s: %s %s", sample.name, plan.action, plan.dataset_id)
            return plan.dataset_id or "<new>"
        return client.register(request, update_if_exists=True, error_on_duplicate=False)

    report = run_batch(iter_samples(), handle, key=lambda s: s.name, max_workers=4)

print(report.summary())
sys.exit(report.exit_code)
```

### Re-running is safe

`register()` looks up the dataset by `(canonical_id, version, project)` before
writing, and — when the dataset already exists — looks up each lineage edge by
`(source_dataset_id, destination_dataset_id, lineage_type)` before creating it.
A second run with `update_if_exists=True, error_on_duplicate=False` therefore
updates the record and creates no duplicate edges.

Lineage `source_ref`s are resolved before anything is written, so an
unresolvable parent raises `LineageResolutionError` without leaving a
half-registered dataset behind.

### Dry run: `plan()`

`plan()` takes the same arguments as `register()`, runs the same decision
logic, and raises the same errors (`DuplicateDatasetError`, `CatalogError` for
multiple matches, `LineageResolutionError`, `ValueError` for conflicting
options) — but it only issues GET requests.

```python
plan = client.plan(request, update_if_exists=True, error_on_duplicate=False)
```

```python
RegistrationPlan(
    action="update",                  # "create" | "update" | "skip"
    dataset_id="0192f3c4-...",        # None when action == "create"
    lineage_to_create=[
        LineageEdgeRequest(
            source_dataset_id="0192a1b2-...",
            destination_dataset_id="0192f3c4-...",
            lineage_type=LineageType.transformed_from,
        ),
    ],                                # edges that already exist are left out
    request=DatasetRequest(...),      # the payload register() would send
)
```

| `action` | When | `register()` then |
|---|---|---|
| `create` | no dataset at these coordinates | POSTs the dataset, then every edge |
| `update` | one match and `update_if_exists=True` | PATCHes it, then creates missing edges |
| `skip` | one match and `error_on_duplicate=False` | leaves it, creates missing edges |

For `create` the new dataset has no id yet, so every edge in
`lineage_to_create` carries `destination_dataset_id=""`; `register()` fills it
in after the POST. `plan()` accepts a bare `DatasetRequest` too, in which case
`lineage_to_create` is always empty.

### Retries: `RetryPolicy`

```python
from catalog_client import CatalogClient, RetryPolicy

client = CatalogClient(
    base_url="https://catalog.example.com",
    api_token="...",
    retry=RetryPolicy(max_attempts=5, base_delay=0.5, max_delay=30.0, jitter=True),
)
```

`retry=None` (the default) sends every request exactly once, as before.
`AsyncCatalogClient` takes the same argument.

| Method | Retried on |
|---|---|
| `GET`, `HEAD`, `PUT`, `DELETE` | `429`, `502`, `503`, `504`, and any network error (`httpx.TransportError`) |
| `POST`, `PATCH` | `429`, and connect errors only (`httpx.ConnectError`, `httpx.ConnectTimeout`) |

A `POST` that timed out *after* it was sent may already have been applied, so
it is not retried — re-running the script is the safe recovery, because
`register()` is idempotent.

- Delay before retry *n* is `min(max_delay, base_delay * 2**(n-1))`; with
  `jitter=True` it is drawn uniformly from `[0, that]` ("full jitter").
- A `Retry-After` header (seconds or an HTTP-date) replaces the computed delay,
  still capped at `max_delay`.
- `max_attempts` counts the first try. When attempts run out the last response
  or error is surfaced as usual (`CatalogServerError`, `CatalogConnectionError`, ...).

### Batches: `run_batch()`

```python
report = run_batch(items, handle, key=lambda item: item.name, max_workers=4)
```

- `handle(item)` returns the dataset id. An `Exception` it raises is recorded
  against that item's key and logged as one `logger.error` line
  (`"<key> failed: <ExcType>: <message>"`, no traceback); the batch carries on.
  `KeyboardInterrupt` and other `BaseException`s still abort the run.
- At most `max_workers` items run at once, and at most `2 * max_workers` are
  pulled from `items` ahead of completion, so a generator over millions of
  records is never materialised.
- `key` defaults to `str`; if `key` itself raises, the item is recorded as
  `item[<index>]`. Pass `logger=` to route failure lines to your own logger.
- Results are recorded in completion order, not input order.

```python
BatchReport(
    succeeded=[("sample-001", "0192f3c4-..."), ...],
    failed=[("sample-017", "NotFoundError: HTTP 404: No dataset found for ...")],
)
report.summary()    # "48 registered, 2 failed: sample-017 (NotFoundError: ...), sample-031 (...)"
                    # "3 registered, 0 failed" when nothing failed
report.summary("planned")  # "3 planned, 0 failed" — for dry runs
report.exit_code    # 1 if anything failed, else 0
```

### Startup check: `check_compatibility()`

```python
from catalog_client import CompatibilityError, check_compatibility

check_compatibility(client)            # sync
await acheck_compatibility(aclient)    # AsyncCatalogClient
```

Fetches `GET <base_url>/api/v1/meta/openapi.json` (with the client's token) and
compares the server's `DatasetRequest.record_schema_version` default with the
one this client writes, as semver (a leading `v` is ignored).

| Server reports | Result |
|---|---|
| newer major version | raises `CompatibilityError`: `server expects record schema v2.0.0, installed catalog-client supports v1.8.0 — upgrade catalog-client` |
| newer minor or patch version | logs a warning and returns `None` |
| same or older | returns `None` |
| no parseable default | logs a warning and returns `None` |

HTTP failures surface as the usual `CatalogError` subclasses
(`AuthenticationError`, `CatalogConnectionError`, ...).

### Local validation: `catalog validate`

Checks a `DatasetRequest` JSON payload against the client's model. No network,
no credentials.

```bash
catalog validate dataset.json
cat dataset.json | catalog validate -
```

Valid — exit `0`, stdout:

```
valid
```

Invalid — exit `1`, one `<dotted.field.path>: <message>` line per error on
stdout (list indices appear as numbers; a non-object payload reports `<root>`):

```
modality: Input should be 'imaging', 'sequencing', 'mass spec', 'text' or 'unknown'
governance: Field required
locations.0.location_uri: Field required
```

A file that is not JSON exits `1` and a missing file exits `4`, both with
`error: <path>: <reason>` on stderr; a missing argument exits `2`. Unknown keys
are ignored by the model, so a misspelt optional field passes validation.

---

## Developer reference

| Module | Contents |
|---|---|
| `plan.py` | `RegistrationPlan`, plus `check_options()` and `decide()` — the one create/update/skip decision used by `plan()` and `register()` on both clients |
| `retry.py` | `RetryPolicy`, `RetryTransport`, `AsyncRetryTransport` (httpx transport wrappers) |
| `batch.py` | `run_batch()`, `BatchReport` |
| `compat.py` | `check_compatibility()`, `acheck_compatibility()` |

Tests sleep through `retry._sleep` / `retry._asleep`; patch those rather than
`time.sleep` to keep retry tests instant.
