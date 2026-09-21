import pytest

from catalog_client.utils.checksum import _parallel


@pytest.fixture(autouse=True)
def _reset_pool_clamp_warnings():
    """The clamp warning fires once per process, so tests must not share it.

    Without this the first test to trigger a clamp consumes the only warning
    and every later assertion sees silence.
    """
    _parallel._warned_pool_clamps.clear()
    yield
    _parallel._warned_pool_clamps.clear()
