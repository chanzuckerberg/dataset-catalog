import base64
from dataclasses import dataclass, field
from typing import Literal

from catalog_client.utils.checksum.algorithm import Algorithm

CHUNK_SIZE = 256 * 1024 * 1024  # 256MB application-level chunks
ChecksumSource = Literal[
    "computed",  # downloaded and hashed locally
    "s3_native",  # read from S3 native checksum (CRC32, CRC64NVME)
    "s3_metadata",  # read from S3 user-defined metadata (blake3, blake2b, crc64)
]


@dataclass
class LocationChecksum:
    value: str | None = None
    algorithm: Algorithm | None = None

    def __bool__(self) -> bool:
        return self.value is not None and self.algorithm is not None


@dataclass
class ChunkRecord:
    index: int
    offset: int
    size: int
    hash: str  # hex digest of this chunk computed independently


@dataclass
class ChecksumResult:
    path: str
    algorithm: Algorithm
    file_hash: str  # whole-file streaming hash/CRC (hex)
    merkle_root: str  # crypto: Merkle root over chunks
    # CRC:    S3-style composite (CRC of raw chunk CRCs)
    is_directory: bool = False
    chunk_size: int = CHUNK_SIZE
    source: ChecksumSource = "computed"
    chunks: list[ChunkRecord] = field(default_factory=list)
    children: dict[str, "ChecksumResult"] = field(default_factory=dict)

    @classmethod
    def _to_base64(cls, hexcode: str) -> str:
        return base64.b64encode(bytes.fromhex(hexcode)).decode()

    @property
    def content_digest(self) -> str:
        """
        The canonical digest identifying this node's content.

        This single value serves both roles: it is what a standalone asset
        reports, and it is what a child contributes to its parent directory.
        Because both paths read the same field, a file hashes to the same
        string whether it is checksummed on its own or as part of a folder —
        and a stored S3 checksum is directly comparable to a computed one.

        For directories file_hash and merkle_root are the same digest, so this
        is well-defined for files and folders alike.
        """
        return self.file_hash

    @property
    def s3_base64(self) -> str:
        """
        Base64-encoded file_hash bytes — the format S3 expects for checksum
        headers (ChecksumCRC32, ChecksumCRC64NVME, etc.).
        Can be used for single-part PutObject.
        """
        return self._to_base64(self.file_hash)

    @property
    def s3_composite_base64(self) -> str:
        """
        Base64-encoded merkle_root bytes.
        Can be used for CompleteMultipartUpload when chunks > 1.

        Only meaningful for file results. On a directory result merkle_root is
        a Merkle root over named children, which is not an S3 composite
        checksum — S3 composites cover ordered, unnamed parts.
        """
        if self.is_directory:
            raise ValueError(
                "s3_composite_base64 is not defined for directory results: "
                "a directory Merkle root is not an S3 multipart composite checksum"
            )
        return self._to_base64(self.merkle_root)
