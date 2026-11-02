"""Models for registering the catalog side of a completed dataset transfer."""

import datetime
import enum

from pydantic import BaseModel, ConfigDict, Field

from catalog_client.models.asset import StoragePlatform, _DataAssetBase


class CopyType(str, enum.Enum):
    """What a copy becomes: its own record, or another location of the same one."""

    fork = "fork"
    mirror = "mirror"


class CopyErrorCode(str, enum.Enum):
    """Why a copy was refused. Only LINEAGE_WRITE_FAILED is worth retrying."""

    COPY_TYPE_NOT_ENABLED = "COPY_TYPE_NOT_ENABLED"
    IDENTITY_UNCHANGED = "IDENTITY_UNCHANGED"
    IDENTITY_TAKEN = "IDENTITY_TAKEN"
    IDENTITY_TOMBSTONED = "IDENTITY_TOMBSTONED"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    ASSET_NOT_IN_SOURCE = "ASSET_NOT_IN_SOURCE"
    MAPPING_INVALID = "MAPPING_INVALID"
    CHECKSUM_UNPAIRED = "CHECKSUM_UNPAIRED"
    LINEAGE_WRITE_FAILED = "LINEAGE_WRITE_FAILED"


class CopyProvenance(BaseModel):
    """How the transfer was performed, as far as the caller cares to say.

    Lands on the lineage edge rather than the dataset: it describes the act
    of copying, which happened once, not the data, which outlives the job
    that moved it. Extra keys are sent through untouched; `_catalog` is
    reserved and the server overwrites it.
    """

    model_config = ConfigDict(extra="allow")

    hermes_job: str | None = Field(
        default=None, description="Hermes job id that performed the transfer"
    )
    transfer_completed_at: datetime.datetime | None = Field(
        default=None, description="When the transfer finished"
    )
    manifest_uri: str | None = Field(
        default=None,
        description="Where the manifest the transfer was drawn from can be read",
    )
    requested_by: str | None = Field(
        default=None, description="Identity that requested the transfer"
    )
    lex_request_id: str | None = Field(
        default=None, description="Lex request authorising the transfer"
    )


class CopyEntry(_DataAssetBase):
    """One asset at the destination, and the source asset it is a copy of.

    A destination asset is a data asset, so it carries the same fields as
    one, plus the two paths that tie it to the transfer. It does not take
    the glob patterns on `DataAssetRequest`: the copy route does not define
    them.
    """

    storage_platform: StoragePlatform = Field(
        description="Storage backend holding the bytes; must be the platform the request names"
    )
    relative_path: str = Field(
        description="The copy's path under the destination root_uri"
    )
    source_relative_path: str | None = Field(
        default=None,
        description="The asset's path within the source dataset, below the source's common root. Checked against the source, not stored; omit it for an asset the destination holds and the source never did",
    )


class DatasetCopyRequest(BaseModel):
    """The destination of a completed transfer of one source dataset.

    No field names the source — the path does — and none carries
    `governance`, which a copy inherits: a transfer does not widen access.
    Extras are forbidden here as they are server-side, so a stray key fails
    locally instead of coming back as a 422.
    """

    model_config = ConfigDict(extra="forbid")

    project: str = Field(min_length=1, description="The copy's project")
    canonical_id: str = Field(min_length=1, description="The copy's canonical id")
    version: str = Field(min_length=1, description="The copy's version")
    storage_platform: StoragePlatform = Field(
        description="Platform holding the destination copy"
    )
    root_uri: str = Field(
        description="Prefix every destination location_uri sits under"
    )
    entries: list[CopyEntry] = Field(
        min_length=1,
        description="One entry per asset at the destination. The set need not cover the source",
    )
    lineage_metadata: CopyProvenance = Field(
        description="Transfer provenance, recorded on the lineage edge"
    )


class DatasetCopyResponse(BaseModel):
    """What the copy resolved to — the same values on a create and on its replay."""

    copy_type: CopyType = Field(description="Whether the copy is a fork or a mirror")
    dataset_id: str = Field(description="The dataset holding the copy")
    project: str = Field(description="The copy's project")
    canonical_id: str = Field(description="The copy's canonical id")
    version: str = Field(description="The copy's version")
    lineage_edge_id: str = Field(
        description="The copy_of edge from the source to the copy"
    )


class CopyErrorDetail(BaseModel):
    """The `detail` object a refused copy carries, in place of a plain string."""

    code: CopyErrorCode = Field(description="Why the copy was refused")
    message: str = Field(description="Human-readable explanation")
    retryable: bool = Field(description="Whether retrying the same request can help")
