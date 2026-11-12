"""Safe text extraction from resume documents.

Supported: text-based PDF (via pypdf) and DOCX (Office Open XML, read directly
from the ZIP container). Not supported, and reported as such:

* scanned / image-only PDFs - there is no OCR in TalentSignal. A PDF whose
  text layer is (nearly) empty fails with code ``no_text_layer``;
* encrypted PDFs that need a password (``encrypted``);
* legacy ``.doc`` / ``.rtf`` / images (rejected before extraction).

Safety:
* nothing embedded in a document is executed - pypdf only parses text
  operators; DOCX is read as XML text with regular expressions (no XML
  entity expansion, no macros);
* sizes are capped: file bytes, PDF pages, DOCX uncompressed XML size;
* lines that state personal attributes irrelevant to the job (date of birth,
  gender, marital status, nationality, religion, ...) are redacted from the
  stored text and never parsed.

Provenance: every line keeps its page number (PDF; ``None`` for DOCX, which
has no fixed pages) and its 1-based line number within that page, so every
extracted fact can point back to its source.
"""
from __future__ import annotations

import html
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_RESUME_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 30
MAX_DOCX_XML_BYTES = 20 * 1024 * 1024
MIN_TEXT_CHARS = 120          # below this the document is treated as having no text layer
MAX_LINE_CHARS = 1000

CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
SENSITIVE = re.compile(
    r"^\s*(date\s+of\s+birth|d\.?o\.?b\.?|birth\s*date|age|gender|sex|marital\s+status|nationality|"
    r"religion|caste|father'?s\s+name|mother'?s\s+name|spouse|passport\s+(no|number)|blood\s+group)\b\s*[:\-]",
    re.I)
REDACTED = "[redacted: personal attribute - not used]"


class ExtractionError(Exception):
    """Extraction failed for a reason the recruiter should see."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ExtractedDocument:
    kind: str                       # "pdf" | "docx"
    pages: list[list[str]]          # lines per page (DOCX: a single "page")
    warnings: list[str] = field(default_factory=list)
    redacted_lines: int = 0
    n_pages: int = 0

    def lines(self) -> list[tuple[int | None, int, str]]:
        """(page or None, line number, text) for every non-empty line."""
        out = []
        for p, lines in enumerate(self.pages, start=1):
            for i, text in enumerate(lines, start=1):
                out.append((p if self.kind == "pdf" else None, i, text))
        return out

    @property
    def text(self) -> str:
        return "\n".join(t for _, _, t in self.lines())


def sniff_kind(head: bytes, filename: str) -> str | None:
    """Identify a file by its leading bytes (not by its name alone)."""
    name = filename.lower()
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        if name.endswith(".docx"):
            return "docx"
        if name.endswith(".zip"):
            return "zip"
        return "zip-unknown"
    return None


def _clean_lines(raw_lines: list[str]) -> tuple[list[str], int]:
    out, redacted = [], 0
    for line in raw_lines:
        line = CONTROL.sub(" ", line).replace(" ", " ")
        line = re.sub(r"[ \t]+", " ", line).strip()[:MAX_LINE_CHARS]
        if not line:
            continue
        if SENSITIVE.match(line):
            out.append(REDACTED)
            redacted += 1
            continue
        out.append(line)
    return out, redacted


def extract_pdf(path: str | Path) -> ExtractedDocument:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    # pypdf logs recoverable structure problems; they are reported through
    # ExtractionError / warnings instead of the server console.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception:  # noqa: BLE001 - unsupported encryption types raise various errors
                ok = 0
            if not ok:
                raise ExtractionError("encrypted", "The PDF is password-protected and cannot be read.")
        total = len(reader.pages)
    except ExtractionError:
        raise
    except (PdfReadError, ValueError, KeyError, OSError) as exc:
        raise ExtractionError("corrupted", f"The PDF could not be read ({type(exc).__name__}).") from exc
    warnings = []
    if total > MAX_PDF_PAGES:
        warnings.append(f"Only the first {MAX_PDF_PAGES} of {total} pages were read.")
    pages, redacted = [], 0
    for i in range(min(total, MAX_PDF_PAGES)):
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception:  # noqa: BLE001 - a single broken page should not fail the document
            text = ""
            warnings.append(f"Page {i + 1} could not be read.")
        lines, r = _clean_lines(text.splitlines())
        pages.append(lines)
        redacted += r
    doc = ExtractedDocument("pdf", pages, warnings, redacted, n_pages=total)
    if len(doc.text.replace(REDACTED, "")) < MIN_TEXT_CHARS:
        raise ExtractionError("no_text_layer",
                              "No extractable text was found. The PDF appears to be scanned or image-only; "
                              "OCR is not supported, so it cannot be processed.")
    return doc


_PARA = re.compile(r"<w:p[ >].*?</w:p>|<w:p/>", re.S)
_TEXT = re.compile(r"<w:t(?: [^>]*)?>(.*?)</w:t>|<w:tab/>|<w:br[^>]*/>", re.S)


def extract_docx(path: str | Path) -> ExtractedDocument:
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ExtractionError("corrupted", "The DOCX file is not a valid Office document.") from exc
    with zf:
        try:
            info = zf.getinfo("word/document.xml")
        except KeyError as exc:
            raise ExtractionError("corrupted", "The DOCX file has no document body.") from exc
        if info.file_size > MAX_DOCX_XML_BYTES:
            raise ExtractionError("too_large", "The DOCX document body is too large to process.")
        warnings = []
        if any(n.lower().endswith("vbaproject.bin") for n in zf.namelist()):
            warnings.append("The document contains macros; they were ignored and never executed.")
        xml = zf.read(info).decode("utf-8", errors="replace")
    raw: list[str] = []
    for para in _PARA.findall(xml):
        pieces = []
        for m in _TEXT.finditer(para):
            tok = m.group(0)
            if tok.startswith("<w:tab"):
                pieces.append(" ")
            elif tok.startswith("<w:br"):
                pieces.append("\n")
            else:
                pieces.append(html.unescape(m.group(1)))
        raw.extend("".join(pieces).split("\n"))
    lines, redacted = _clean_lines(raw)
    doc = ExtractedDocument("docx", [lines], warnings, redacted, n_pages=1)
    if len(doc.text.replace(REDACTED, "")) < MIN_TEXT_CHARS:
        raise ExtractionError("no_text", "The document contains too little text to extract a profile.")
    return doc


def extract(path: str | Path, kind: str) -> ExtractedDocument:
    if Path(path).stat().st_size > MAX_RESUME_BYTES:
        raise ExtractionError("too_large", f"Resumes are limited to {MAX_RESUME_BYTES // (1024 * 1024)} MB.")
    if kind == "pdf":
        return extract_pdf(path)
    if kind == "docx":
        return extract_docx(path)
    raise ExtractionError("unsupported_format", "Only PDF and DOCX resumes are supported.")
