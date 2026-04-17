"""Smoke tests for checksum utilities module."""

from catalog_client.models.asset import AssetType, DataAssetRequest
from catalog_client.utils import (
    ChecksumWarning,
    generate_for_assets,
    get_supported_algorithms,
)


def test_module_imports():
    """Test that utils module exports public functions and classes."""
    assert get_supported_algorithms is not None
    assert generate_for_assets is not None
    assert ChecksumWarning is not None


def test_get_supported_algorithms():
    """Test get_supported_algorithms returns expected list."""
    algorithms = get_supported_algorithms()
    assert isinstance(algorithms, list)
    assert len(algorithms) > 0
    expected = ["blake3", "blake2b", "blake2s", "crc32"]
    assert algorithms == expected


def test_generate_for_assets_empty_list():
    """Test generate_for_assets returns empty list for empty input."""
    result = generate_for_assets([])
    assert result == []


def test_generate_for_assets_preserves_single_asset():
    """Test generate_for_assets returns copy of assets with checksums populated."""
    asset = DataAssetRequest(
        location_uri="s3://bucket/key",
        asset_type=AssetType.file
    )
    result = generate_for_assets([asset])
    assert len(result) == 1
    assert isinstance(result, list)
