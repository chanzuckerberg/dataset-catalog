"""Explicit committed-snapshot publication and version resolution."""

from urllib.parse import quote

from catalog_client.client._base import _AsyncBase, _SyncBase


def _release_path(dataset_id: str, version: int) -> str:
    if not dataset_id or type(version) is not int or version < 1:
        raise ValueError(
            "A dataset ID and positive explicit integer version are required"
        )
    return f"releases/{quote(dataset_id, safe='')}/versions/{version}"


class PublicationClient(_SyncBase):
    def publish_committed_snapshot(self, request: dict) -> dict:
        """Bind an already committed snapshot using the Catalog release API."""
        return self._post("publications/committed-snapshots", json=request).json()

    def resolve_release(self, dataset_id: str, version: int) -> dict:
        """Resolve exactly one scientific release. There is no latest default."""
        return self._get(_release_path(dataset_id, version)).json()

    def resolve_repository(self, **selectors: str) -> dict:
        """Resolve a producer handle to its current published base."""
        if not selectors or set(selectors) - {
            "repository_uri",
            "repository_id",
            "source_key",
        }:
            raise ValueError("Supply repository_uri, repository_id, or source_key")
        return self._get("publications/repositories/resolve", params=selectors).json()


class AsyncPublicationClient(_AsyncBase):
    async def publish_committed_snapshot(self, request: dict) -> dict:
        return (
            await self._post("publications/committed-snapshots", json=request)
        ).json()

    async def resolve_release(self, dataset_id: str, version: int) -> dict:
        return (await self._get(_release_path(dataset_id, version))).json()

    async def resolve_repository(self, **selectors: str) -> dict:
        if not selectors or set(selectors) - {
            "repository_uri",
            "repository_id",
            "source_key",
        }:
            raise ValueError("Supply repository_uri, repository_id, or source_key")
        return (
            await self._get("publications/repositories/resolve", params=selectors)
        ).json()
