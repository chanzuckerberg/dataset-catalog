"""Checksum generation utilities for DataAssetRequest objects."""

from __future__ import annotations

import warnings  # noqa: F401 — used by generate_for_assets in subsequent implementation
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catalog_client.models.asset import DataAssetRequest


class ChecksumWarning(UserWarning):
    """Warning class for checksum generation issues."""
    pass


def get_supported_algorithms() -> list[str]:
    """Returns list of supported checksum algorithms.

    Returns:
        List of algorithm names: ['blake3', 'blake2b', 'blake2s', 'crc32']
    """
    return ['blake3', 'blake2b', 'blake2s', 'crc32']


def generate_for_assets(
    assets: list[DataAssetRequest],
    algorithm: str | None = None
) -> list[DataAssetRequest]:
    """Generate checksums for assets on supported storage platforms.

    Args:
        assets: List of assets to process
        algorithm: Checksum algorithm ('blake3', 'blake2b', 'blake2s', 'crc32').
                  If None, defaults to blake3 except for S3 where existing CRC32 is preferred.

    Returns:
        New list with checksums populated for supported assets.
        Issues warnings for unsupported platforms or failures.

    Supported platforms: s3, hpc, coreweave
    Supported algorithms: blake3, blake2b, blake2s, crc32
    """
    # TODO: Implement in subsequent tasks
    return assets.copy()
