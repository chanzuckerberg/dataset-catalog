"""
Runs the fast tier of the checksum eval as part of the normal test suite.

The eval exists because the unit suite cannot check some things about itself
(see evals/README.md), but its cheap tier costs about a second, so there is no
reason for CI to miss a regression it would have caught. Only the fast tier runs
here: `full` generates up to 1GB of fixtures and `aws` needs credentials.

The eval reports rather than asserts, so this bridge turns its report into
assertions — one test per dimension, so a failure names the dimension rather
than "the eval failed".

Deselect with `pytest -m "not eval"`.
"""

import pytest

from evals.checksum.dimensions import DIMENSIONS
from evals.checksum.harness import Context, Status, Tier, run_dimension

pytestmark = pytest.mark.eval

# scale and aws_native self-skip below the tier they need; running them here
# just produces one skip check each, which is the honest record.
DIMENSION_NAMES = sorted(DIMENSIONS)


@pytest.fixture(scope="module")
def fast_run(tmp_path_factory):
    """Run every dimension once at the fast tier and index the results by name."""
    ctx = Context(tier=Tier.fast, workdir=tmp_path_factory.mktemp("checksum-eval"))
    return {
        name: run_dimension(name, DIMENSIONS[name], ctx) for name in DIMENSION_NAMES
    }


@pytest.mark.parametrize("dimension", DIMENSION_NAMES)
def test_eval_dimension_has_no_failures(fast_run, dimension):
    run = fast_run[dimension]
    problems = [check for check in run.checks if check.counts_against_us]
    assert not problems, "\n".join(
        f"{check.status.value.upper()} {check.id}: {check.message}"
        for check in problems
    )


def test_eval_actually_ran_checks(fast_run):
    """
    Guard against a silently empty eval.

    A dimension that yields nothing — a corpus filtered down to zero cases, an
    import that quietly no-ops — would make every test above pass while checking
    nothing at all.
    """
    verdicts = {
        name: sum(1 for check in run.checks if check.status is not Status.skipped)
        for name, run in fast_run.items()
    }
    expected_to_run = {"conformance", "golden", "invariance", "sizes"}
    empty = {name for name in expected_to_run if not verdicts[name]}
    assert not empty, f"dimensions produced no verdicts at the fast tier: {empty}"
