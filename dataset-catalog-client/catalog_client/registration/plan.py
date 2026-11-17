"""RegistrationPlan and the create/update/skip decision shared by register() and plan()."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from catalog_client.exceptions import CatalogError, DuplicateDatasetError
from catalog_client.models.dataset import DatasetRef, DatasetRequest, DatasetResponse
from catalog_client.models.lineage import LineageEdgeRequest
from catalog_client.registration.request import RegistrationRequest

Action = Literal["create", "update", "skip"]


@dataclass(frozen=True)
class RegistrationPlan:
    """What register() would do for a request, computed with GET requests only.

    For action == "create" the dataset id does not exist yet, so each edge in
    lineage_to_create carries an empty destination_dataset_id.
    """

    action: Action
    dataset_id: str | None
    lineage_to_create: list[LineageEdgeRequest]
    request: DatasetRequest


def to_dataset_request(request: RegistrationRequest | DatasetRequest) -> DatasetRequest:
    if isinstance(request, RegistrationRequest):
        return request.to_dataset_request()
    return request


def check_options(
    dataset: DatasetRequest, update_if_exists: bool, error_on_duplicate: bool
) -> DatasetRef:
    """Reject bad options before any request; returns the ref to look up."""
    if update_if_exists and error_on_duplicate:
        raise ValueError("update_if_exists and error_on_duplicate cannot both be True")
    if dataset.project is None:
        raise ValueError("project is required to register a dataset")
    return DatasetRef(dataset.canonical_id, dataset.version, dataset.project)


def decide(
    ref: DatasetRef,
    existing: Sequence[DatasetResponse],
    update_if_exists: bool,
    error_on_duplicate: bool,
) -> tuple[Action, str | None]:
    if not existing:
        return "create", None

    if error_on_duplicate:
        raise DuplicateDatasetError(ref)
    if len(existing) > 1:
        raise CatalogError(f"Multiple datasets found ({len(existing)}) for {ref!r}")

    return ("update" if update_if_exists else "skip"), existing[0].id
