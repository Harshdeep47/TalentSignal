"""Dataset fingerprints.

The reference implementation hashed only the first and last megabyte of the
file, so an edit in the middle went unnoticed. TalentSignal hashes every byte
with BLAKE2b (fast, cryptographically strong). On a 465 MB file this costs
well under two seconds on a laptop SSD, which is negligible next to indexing.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK = 4 * 1024 * 1024


def file_fingerprint(path: str | Path) -> str:
    h = hashlib.blake2b(digest_size=20)
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
            size += len(chunk)
    return f"b2-{size}-{h.hexdigest()}"
