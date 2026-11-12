"""Safe iteration over ZIP archives of resumes.

Archive members are never extracted to paths derived from their names (so
``../../etc/passwd`` style "zip slip" entries cannot write outside the target).
Each member is streamed into a server-chosen file with byte limits enforced
while copying - the sizes declared in the archive are checked first but not
trusted.

Rejected members are reported (not silently skipped) so the processing
dashboard can show them as failed documents:
  encrypted members, nested archives, unsupported extensions, oversized
  members, suspicious compression ratios (zip bombs), too many members, and
  archives whose total uncompressed size exceeds the limit.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO, Iterator

from engine.resumes.extract import MAX_RESUME_BYTES

MAX_MEMBERS = 20_000
MAX_TOTAL_UNCOMPRESSED = 6 * 1024 ** 3
MAX_RATIO = 100            # uncompressed / compressed, checked for members over 1 MB
ACCEPTED = (".pdf", ".docx")
IGNORED_PARTS = ("__MACOSX/",)
COPY_CHUNK = 1024 * 1024


class ZipArchiveError(ValueError):
    pass


@dataclass
class ZipMember:
    info: zipfile.ZipInfo
    display_name: str
    problem_code: str | None = None
    problem: str | None = None


def display_name(raw: str) -> str:
    """Basename only - directory components (including '..') are dropped."""
    return PurePosixPath(raw.replace("\\", "/")).name or "unnamed"


def iter_members(zf: zipfile.ZipFile) -> Iterator[ZipMember]:
    infos = zf.infolist()
    files = [i for i in infos if not i.is_dir() and not any(p in i.filename for p in IGNORED_PARTS)
             and not display_name(i.filename).startswith(".")]
    if len(files) > MAX_MEMBERS:
        raise ZipArchiveError(f"The archive has {len(files):,} files; the limit is {MAX_MEMBERS:,}.")
    if sum(i.file_size for i in files) > MAX_TOTAL_UNCOMPRESSED:
        raise ZipArchiveError("The archive expands to more than the allowed total size.")
    for info in files:
        name = display_name(info.filename)
        low = name.lower()
        m = ZipMember(info, name)
        if info.flag_bits & 0x1:
            m.problem_code, m.problem = "encrypted", "Encrypted archive entries are not supported."
        elif low.endswith((".zip", ".7z", ".rar", ".tar", ".gz")):
            m.problem_code, m.problem = "nested_archive", "Archives inside archives are not supported."
        elif not low.endswith(ACCEPTED):
            m.problem_code, m.problem = "unsupported_format", "Only PDF and DOCX resumes are supported."
        elif info.file_size > MAX_RESUME_BYTES:
            m.problem_code, m.problem = "too_large", f"Resumes are limited to {MAX_RESUME_BYTES // (1024 * 1024)} MB."
        elif info.file_size > 1024 * 1024 and info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
            m.problem_code, m.problem = "suspicious_archive_entry", "Suspicious compression ratio; entry skipped."
        yield m


def copy_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, out: BinaryIO, limit: int = MAX_RESUME_BYTES) -> int:
    """Stream one member into ``out``; raises ZipArchiveError if it exceeds ``limit``."""
    written = 0
    with zf.open(info) as src:
        while chunk := src.read(COPY_CHUNK):
            written += len(chunk)
            if written > limit:
                raise ZipArchiveError("Entry is larger than declared or exceeds the size limit.")
            out.write(chunk)
    return written
