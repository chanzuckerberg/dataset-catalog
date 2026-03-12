import httpx
import pytest

from catalog_client.exceptions import (
    AuthenticationError,
    CatalogConnectionError,
    CatalogError,
    CatalogHTTPError,
    CatalogServerError,
    LineageResolutionError,
    NotFoundError,
    ValidationError,
    raise_for_status,
)


def _mock_response(status_code: int, body: dict) -> httpx.Response:
    return httpx.Response(status_code, json=body, request=httpx.Request("GET", "http://x"))


def test_raise_for_status_401():
    with pytest.raises(AuthenticationError) as exc_info:
        raise_for_status(_mock_response(401, {"detail": "Unauthorized"}))
    assert exc_info.value.status_code == 401
    assert "Unauthorized" in str(exc_info.value)


def test_raise_for_status_404():
    with pytest.raises(NotFoundError) as exc_info:
        raise_for_status(_mock_response(404, {"detail": "Not found"}))
    assert exc_info.value.status_code == 404


def test_raise_for_status_422():
    detail = [{"loc": ["body", "name"], "msg": "field required", "type": "missing"}]
    with pytest.raises(ValidationError) as exc_info:
        raise_for_status(_mock_response(422, {"detail": detail}))
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == detail


def test_raise_for_status_500():
    with pytest.raises(CatalogServerError) as exc_info:
        raise_for_status(_mock_response(500, {"detail": "boom"}))
    assert exc_info.value.status_code == 500


def test_raise_for_status_200_does_not_raise():
    raise_for_status(_mock_response(200, {}))


def test_lineage_resolution_error_carries_ref():
    from catalog_client.models.dataset import DatasetRef
    ref = DatasetRef(canonical_id="ds-1", version="1.0.0", project="proj")
    err = LineageResolutionError(ref=ref, reason="no results")
    assert err.ref == ref
    assert "ds-1" in str(err)


def test_catalog_connection_error_is_catalog_error():
    err = CatalogConnectionError("network failure")
    assert isinstance(err, CatalogError)


def test_hierarchy():
    assert issubclass(AuthenticationError, CatalogHTTPError)
    assert issubclass(NotFoundError, CatalogHTTPError)
    assert issubclass(ValidationError, CatalogHTTPError)
    assert issubclass(CatalogServerError, CatalogHTTPError)
    assert issubclass(CatalogHTTPError, CatalogError)
    assert issubclass(CatalogConnectionError, CatalogError)
    assert issubclass(LineageResolutionError, CatalogError)
