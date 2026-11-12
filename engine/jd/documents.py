"""Extract plain text from uploaded job-description documents.

Supported: .txt, .md, .docx. DOCX is read directly from its XML (a .docx is a
ZIP archive) so no extra dependency is needed. The archive is size-checked
before decompression to block "zip bomb" uploads.
"""
from __future__ import annotations

import html
import io
import re
import zipfile

MAX_DOCX_UNCOMPRESSED = 20 * 1024 * 1024
SUPPORTED = (".txt", ".md", ".docx")


class DocumentError(ValueError):
    pass


def docx_to_text(data: bytes) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocumentError("The file is not a valid .docx document.") from exc
    try:
        info = zf.getinfo("word/document.xml")
    except KeyError as exc:
        raise DocumentError("The .docx file has no document body.") from exc
    if info.file_size > MAX_DOCX_UNCOMPRESSED:
        raise DocumentError("The .docx document is too large to process.")
    xml = zf.read(info).decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    xml = re.sub(r"</w:tc>", " | ", xml)
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".docx"):
        return docx_to_text(data)
    if name.endswith((".txt", ".md")):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("latin-1")
    raise DocumentError(f"Unsupported job description format. Use one of: {', '.join(SUPPORTED)}.")
