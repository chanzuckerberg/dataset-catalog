"""
Subprocess probe: hash one file and report peak memory.

Run as a child process on purpose. `ru_maxrss` is a high-water mark that never
comes back down, so measuring it inside the eval process would report the peak
of everything the eval had already done — including the 1GB fixture it just
generated. A fresh interpreter that does nothing but import, baseline, and hash
gives a delta attributable to the hashing itself.

    python -m evals.checksum._probe <path> <algorithm> [chunk_size] [read_buffer]

Prints one JSON object on stdout.
"""

from __future__ import annotations

import json
import resource
import sys
import time


def _maxrss_bytes() -> int:
    """
    ru_maxrss, normalised to bytes.

    Linux reports kilobytes, macOS reports bytes. Getting this wrong would make
    the memory ceiling 1024x too loose on one platform and 1024x too tight on
    the other.
    """
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw if sys.platform == "darwin" else raw * 1024


def main(argv: list[str]) -> int:
    path, algorithm_name = argv[1], argv[2]
    chunk_size = int(argv[3]) if len(argv) > 3 else None
    read_buffer = int(argv[4]) if len(argv) > 4 else None

    from catalog_client.utils.checksum.algorithm import Algorithm, new_hasher
    from catalog_client.utils.checksum.hashing import compute_checksum_localfs

    algorithm = Algorithm(algorithm_name)
    # Instantiate the hasher before the baseline so the extension module's
    # import and first allocation are not charged to the hashing itself.
    new_hasher(algorithm)

    if chunk_size is not None or read_buffer is not None:
        from catalog_client.utils.checksum import hashing

        if chunk_size is not None:
            hashing.CHUNK_SIZE = chunk_size
        if read_buffer is not None:
            hashing.READ_BUFFER = read_buffer

    baseline = _maxrss_bytes()
    started = time.perf_counter()
    result = compute_checksum_localfs(path, algorithm)
    elapsed = time.perf_counter() - started
    peak = _maxrss_bytes()

    json.dump(
        {
            "content_digest": result.content_digest,
            "merkle_root": result.merkle_root,
            "chunk_count": len(result.chunks),
            "total_size": result.total_size,
            "seconds": elapsed,
            "baseline_rss_bytes": baseline,
            "peak_rss_bytes": peak,
            "peak_rss_delta_bytes": max(0, peak - baseline),
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
