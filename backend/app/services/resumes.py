"""Resume ingestion service: batches, uploads, background processing, review
and publishing into the existing dataset/ranking pipeline.

Lifecycle of one document::

    upload -> queued -> processing -> needs_review -> approved -> (publish)
                                \\-> failed           \\-> rejected
    upload -> duplicate   (byte-identical to a document already uploaded by this session)
    upload -> failed      (unsupported format, oversized, unsafe archive entry)

Storage (all under ``data/resumes/<batch id>/``, server-chosen names only):

* ``<doc id>.pdf|.docx``  the original file, kept unchanged;
* ``<doc id>.json``       the extraction (facts with provenance), the page/line
                          text, the mapped candidate record and any edits.

The current candidate record (parsed or corrected) is also kept in the
``record_json`` column, so publishing streams rows from SQLite instead of
opening one file per document (on Windows each fresh file open was measured
at ~20 ms - ten thousand of them dominated publish time).

Publishing writes the approved candidate records to a JSONL file and
registers it through ``DatasetService`` - from there indexing, ranking,
explanations, integrity checks and exports are exactly the existing ones.
Contact details stay in the extraction file; they are not part of the
candidate record and therefore never reach an index, a run or an export.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import BinaryIO, Iterable

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import safe_display_name
from app.database.db import Database, new_id, now
from app.services.datasets import DatasetService
from app.services.jobs import JobContext, JobManager
from engine.ingestion.validation import Normalizer
from engine.resumes.extract import MAX_RESUME_BYTES, ExtractionError, extract, sniff_kind
from engine.resumes.parse import parse_resume, to_candidate_record
from engine.resumes.zipsafe import ZipArchiveError, copy_member, iter_members

log = logging.getLogger("talentsignal.resumes")

STATUSES = ("queued", "processing", "needs_review", "approved", "rejected", "failed", "duplicate")
REVIEWABLE = ("needs_review", "approved", "rejected")
MAX_FILES_PER_REQUEST = 500
MAX_DOCS_PER_BATCH = 20_000
COPY_CHUNK = 1024 * 1024
FETCH_CHUNK = 200
DOC_COLUMNS = ("id", "batch_id", "filename", "kind", "size_bytes", "status", "error_code", "error", "duplicate_of",
               "possible_duplicate_of", "candidate_id", "display_name", "title", "n_pages", "n_warnings", "edited",
               "created_at", "updated_at")


class _HashingWriter:
    """File wrapper that hashes and counts bytes as they are written."""

    def __init__(self, f: BinaryIO, limit: int):
        self.f, self.limit, self.n = f, limit, 0
        self.h = hashlib.sha256()
        self.head = b""

    def write(self, chunk: bytes) -> None:
        self.n += len(chunk)
        if self.n > self.limit:
            raise ZipArchiveError("too_large")
        if len(self.head) < 8:
            self.head = (self.head + chunk)[:8]
        self.h.update(chunk)
        self.f.write(chunk)


def _contact_key(extraction: dict) -> str | None:
    """Hash of the first e-mail (else phone digits) - used only to warn about
    probable duplicates. The raw value is never stored in the database."""
    c = extraction.get("contact") or {}
    if c.get("emails"):
        raw = c["emails"][0]["value"].strip().lower()
    elif c.get("phones"):
        raw = re.sub(r"\D", "", c["phones"][0]["value"])[-10:]
    else:
        return None
    return hashlib.sha256(("ts-contact:" + raw).encode()).hexdigest()


def _flatten(obj, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(obj, list):
        out[prefix] = json.dumps(obj, sort_keys=True, default=str)
    else:
        out[prefix] = obj
    return out


def _write_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)


class ResumeService:
    def __init__(self, settings: Settings, db: Database, jobs: JobManager, datasets: DatasetService):
        self.s = settings
        self.db = db
        self.jobs = jobs
        self.datasets = datasets
        # Documents that were mid-processing when the server stopped go back to the queue.
        db.execute("UPDATE resume_documents SET status='queued', updated_at=? WHERE status='processing'", (now(),))

    # ------------------------------------------------------------------ batches
    def create_batch(self, owner: str, name: str) -> dict:
        row = {"id": new_id(), "owner": owner, "name": safe_display_name(name, 120) if name.strip() else "Resumes",
               "last_dataset_id": None, "created_at": now(), "updated_at": now()}
        self.db.insert("resume_batches", row)
        self.batch_dir(row["id"]).mkdir(parents=True, exist_ok=True)
        self.db.log_activity(owner, "resumes", f"Resume batch '{row['name']}' created", row["id"])
        return self.batch_json(row)

    def batch_dir(self, batch_id: str) -> Path:
        return self.s.resumes_dir / batch_id

    def _batch(self, batch_id: str, owner: str) -> dict:
        row = self.db.one("SELECT * FROM resume_batches WHERE id=? AND owner=?", (batch_id, owner))
        if not row:
            raise AppError(404, "batch_not_found", "Resume batch not found.")
        return row

    def counts(self, batch_id: str) -> dict:
        rows = self.db.query("SELECT status, COUNT(*) AS n FROM resume_documents WHERE batch_id=? GROUP BY status",
                             (batch_id,))
        c = {s: 0 for s in STATUSES}
        c.update({r["status"]: r["n"] for r in rows})
        c["total"] = sum(c[s] for s in STATUSES)
        c["processed"] = c["needs_review"] + c["approved"] + c["rejected"]
        return c

    def latest_job(self, batch_id: str) -> dict | None:
        return self.db.one("SELECT * FROM jobs WHERE target_id=? AND kind='resume' ORDER BY created_at DESC LIMIT 1",
                           (batch_id,))

    def batch_json(self, row: dict) -> dict:
        out = {k: row[k] for k in ("id", "name", "last_dataset_id", "created_at", "updated_at")}
        out["counts"] = self.counts(row["id"])
        out["job"] = self.latest_job(row["id"])
        out["last_dataset"] = None
        if row["last_dataset_id"]:
            d = self.db.one("SELECT id, name, status, n_candidates, error FROM datasets WHERE id=?",
                            (row["last_dataset_id"],))
            out["last_dataset"] = d
        return out

    def list_batches(self, owner: str) -> list[dict]:
        return [self.batch_json(r) for r in
                self.db.query("SELECT * FROM resume_batches WHERE owner=? ORDER BY created_at DESC", (owner,))]

    def get_batch(self, batch_id: str, owner: str) -> dict:
        return self.batch_json(self._batch(batch_id, owner))

    def delete_batch(self, batch_id: str, owner: str) -> None:
        row = self._batch(batch_id, owner)
        job = self.latest_job(batch_id)
        if job and job["status"] in ("queued", "running"):
            self.jobs.cancel(job["id"])
        self.db.execute("DELETE FROM resume_batches WHERE id=?", (batch_id,))
        shutil.rmtree(self.batch_dir(batch_id), ignore_errors=True)
        self.db.log_activity(owner, "resumes", f"Resume batch '{row['name']}' deleted (published datasets kept)",
                             batch_id)

    # ------------------------------------------------------------------ uploads
    def add_files(self, batch_id: str, owner: str, files: Iterable[tuple[str, BinaryIO]]) -> dict:
        """Store uploaded PDF/DOCX files and ZIP archives; returns a summary.

        Every file (and every archive member) becomes a document row - files
        that cannot be used are recorded as failed with a reason, so nothing
        disappears silently. Processing starts automatically."""
        batch = self._batch(batch_id, owner)
        files = list(files)
        if not files:
            raise AppError(400, "no_files", "No files were uploaded.")
        if len(files) > MAX_FILES_PER_REQUEST:
            raise AppError(413, "too_many_files",
                           f"Upload at most {MAX_FILES_PER_REQUEST} files at once; use a ZIP archive for more.")
        bdir = self.batch_dir(batch_id)
        bdir.mkdir(parents=True, exist_ok=True)
        existing = self.counts(batch_id)["total"]
        seen: dict[str, str] = {}
        rows: list[dict] = []
        summary = {"received": 0, "queued": 0, "duplicate": 0, "failed": 0, "archives": 0}

        def room() -> None:
            if existing + len(rows) >= MAX_DOCS_PER_BATCH:
                raise AppError(413, "batch_full", f"A batch holds at most {MAX_DOCS_PER_BATCH:,} documents.")

        for raw_name, stream in files:
            name = safe_display_name(raw_name, 160)
            tmp = bdir / f".upload-{new_id()}"
            zip_limit = self.s.max_resume_zip_mb * 1024 * 1024
            try:
                with open(tmp, "wb") as f:
                    w = _HashingWriter(f, max(zip_limit, MAX_RESUME_BYTES))
                    while chunk := stream.read(COPY_CHUNK):
                        w.write(chunk)
            except ZipArchiveError:
                tmp.unlink(missing_ok=True)
                summary["received"] += 1
                room()
                rows.append(self._failed_row(batch_id, owner, name, None, w.n, "too_large",
                                             f"The upload exceeds the {self.s.max_resume_zip_mb} MB limit."))
                continue
            kind = sniff_kind(w.head, name)
            if kind == "zip":
                summary["archives"] += 1
                try:
                    self._add_archive(batch_id, owner, tmp, rows, seen, summary, room)
                except (ZipArchiveError, zipfile.BadZipFile) as exc:
                    summary["received"] += 1
                    room()
                    msg = str(exc) if isinstance(exc, ZipArchiveError) else "The ZIP archive is corrupted."
                    rows.append(self._failed_row(batch_id, owner, name, None, w.n, "invalid_archive", msg))
                finally:
                    tmp.unlink(missing_ok=True)
                continue
            summary["received"] += 1
            room()
            rows.append(self._file_row(batch_id, owner, name, tmp, kind, w.n, w.h.hexdigest(), seen))
        self.db.insert_many("resume_documents", rows)
        for r in rows:
            summary[r["status"] if r["status"] in summary else "failed"] += 1
        self.db.update("resume_batches", batch_id, updated_at=now())
        self.db.log_activity(owner, "resumes", f"{summary['received']:,} resume file(s) added to '{batch['name']}'",
                             batch_id)
        if summary["queued"]:
            self.start_processing(batch_id, owner)
        return summary

    def _add_archive(self, batch_id, owner, path: Path, rows, seen, summary, room) -> None:
        with zipfile.ZipFile(path) as zf:
            for m in iter_members(zf):
                summary["received"] += 1
                room()
                if m.problem_code:
                    rows.append(self._failed_row(batch_id, owner, safe_display_name(m.display_name, 160), None,
                                                 m.info.file_size, m.problem_code, m.problem))
                    continue
                tmp = self.batch_dir(batch_id) / f".member-{new_id()}"
                try:
                    with open(tmp, "wb") as f:
                        w = _HashingWriter(f, MAX_RESUME_BYTES)
                        copy_member(zf, m.info, w, MAX_RESUME_BYTES)
                except (ZipArchiveError, zipfile.BadZipFile, OSError, EOFError) as exc:
                    tmp.unlink(missing_ok=True)
                    code = "too_large" if isinstance(exc, ZipArchiveError) else "corrupted"
                    msg = ("The entry exceeds the per-resume size limit." if code == "too_large"
                           else "The archive entry could not be read.")
                    rows.append(self._failed_row(batch_id, owner, safe_display_name(m.display_name, 160), None,
                                                 m.info.file_size, code, msg))
                    continue
                name = safe_display_name(m.display_name, 160)
                rows.append(self._file_row(batch_id, owner, name, tmp, sniff_kind(w.head, name), w.n,
                                           w.h.hexdigest(), seen))

    def _base_row(self, batch_id, owner, name, kind, size, status) -> dict:
        return {"id": new_id(), "batch_id": batch_id, "owner": owner, "filename": name, "kind": kind,
                "size_bytes": size, "sha256": None, "stored_path": None, "status": status, "error_code": None,
                "error": None, "duplicate_of": None, "possible_duplicate_of": None, "candidate_id": None,
                "display_name": None, "title": None, "n_pages": None, "n_warnings": None, "contact_key": None,
                "extraction_path": None, "edited": 0, "created_at": now(), "updated_at": now()}

    def _failed_row(self, batch_id, owner, name, kind, size, code, message) -> dict:
        row = self._base_row(batch_id, owner, name, kind, size, "failed")
        row.update(error_code=code, error=message)
        return row

    def _file_row(self, batch_id, owner, name, tmp: Path, kind, size, digest, seen) -> dict:
        """Classify one stored file: unsupported, duplicate, or queued (file kept)."""
        ext = Path(name).suffix.lower()
        if (kind, ext) not in (("pdf", ".pdf"), ("docx", ".docx")):
            tmp.unlink(missing_ok=True)
            if ext in (".pdf", ".docx") or kind in ("pdf", "docx"):
                msg = "The file content does not match its extension (checked by file signature)."
            elif ext == ".doc":
                msg = "Legacy .doc files are not supported; save the resume as .docx or PDF."
            else:
                msg = "Only PDF and DOCX resumes are supported."
            return self._failed_row(self._bid(tmp), owner, name, None, size, "unsupported_format", msg)
        if size == 0:
            tmp.unlink(missing_ok=True)
            return self._failed_row(self._bid(tmp), owner, name, kind, size, "empty_file", "The file is empty.")
        row = self._base_row(self._bid(tmp), owner, name, kind, size, "queued")
        row["sha256"] = digest
        original = seen.get(digest) or (self.db.one(
            "SELECT id FROM resume_documents WHERE owner=? AND sha256=? AND status!='duplicate' "
            "ORDER BY created_at LIMIT 1", (owner, digest)) or {}).get("id")
        if original:
            tmp.unlink(missing_ok=True)
            row.update(status="duplicate", duplicate_of=original, error_code="duplicate",
                       error="Identical to a file uploaded earlier; the earlier copy is kept.")
            return row
        seen[digest] = row["id"]
        dest = tmp.with_name(f"{row['id']}.{kind}")
        os.replace(tmp, dest)
        row["stored_path"] = str(dest)
        return row

    @staticmethod
    def _bid(tmp: Path) -> str:
        return tmp.parent.name

    # ------------------------------------------------------------------ processing
    def start_processing(self, batch_id: str, owner: str, retry_failed: bool = False) -> dict | None:
        self._batch(batch_id, owner)
        if retry_failed:
            self.db.execute("UPDATE resume_documents SET status='queued', error=NULL, error_code=NULL, updated_at=? "
                            "WHERE batch_id=? AND status='failed' AND stored_path IS NOT NULL", (now(), batch_id))
        job = self.latest_job(batch_id)
        if job and job["status"] in ("queued", "running"):
            return job
        if not self.db.one("SELECT 1 FROM resume_documents WHERE batch_id=? AND status='queued' LIMIT 1", (batch_id,)):
            return job
        job_id = self.jobs.submit("resume", batch_id, owner, lambda ctx: self._process(ctx, batch_id, owner))
        return self.jobs.get(job_id)

    def _process(self, ctx: JobContext, batch_id: str, owner: str) -> None:
        """Process queued documents one at a time (bounded memory: one
        document's text in memory, results written to disk immediately).
        Documents added while the job runs are picked up by the same job."""
        done = 0
        while True:
            queued = self.db.query("SELECT * FROM resume_documents WHERE batch_id=? AND status='queued' "
                                   "ORDER BY created_at, id LIMIT ?", (batch_id, FETCH_CHUNK))
            if not queued:
                break
            remaining = self.db.one("SELECT COUNT(*) AS n FROM resume_documents WHERE batch_id=? AND status='queued'",
                                    (batch_id,))["n"]
            total = done + remaining
            for doc in queued:
                ctx.check()
                self.db.update("resume_documents", doc["id"], status="processing", updated_at=now())
                try:
                    self._process_one(doc, batch_id, owner)
                except Exception as exc:  # noqa: BLE001 - one bad document must not stop the batch
                    log.exception("Resume %s could not be processed", doc["id"])
                    self.db.update("resume_documents", doc["id"], status="failed", error_code="processing_failed",
                                   error=f"Unexpected processing error ({type(exc).__name__}).", updated_at=now())
                done += 1
                ctx.progress(done / total, f"Processed {done:,} of {total:,} document(s)")
        self.db.update("resume_batches", batch_id, updated_at=now())
        self.db.log_activity(owner, "resumes", f"Processed {done:,} resume(s)", batch_id)

    def _process_one(self, doc: dict, batch_id: str, owner: str) -> None:
        try:
            extracted = extract(doc["stored_path"], doc["kind"])
            extraction = parse_resume(extracted)
        except ExtractionError as exc:
            self.db.update("resume_documents", doc["id"], status="failed", error_code=exc.code, error=exc.message,
                           updated_at=now())
            return
        cid = f"RES_{batch_id[:6]}_{doc['id'][:8]}"
        parsed = to_candidate_record(extraction, cid, fallback_name=Path(doc["filename"]).stem[:80])
        record, issues = Normalizer().normalize(parsed)
        key = _contact_key(extraction)
        possible = None
        if key:
            hit = self.db.one("SELECT id FROM resume_documents WHERE owner=? AND contact_key=? AND id!=? "
                              "AND status NOT IN ('duplicate','failed') ORDER BY created_at LIMIT 1",
                              (owner, key, doc["id"]))
            possible = hit["id"] if hit else None
        warnings = list(extraction["warnings"])
        if possible:
            warnings.append("Another resume in your uploads has the same e-mail address or phone number "
                            "(possible duplicate candidate).")
        extraction["warnings"] = warnings
        path = self.batch_dir(batch_id) / f"{doc['id']}.json"
        _write_json(path, {"extraction": extraction, "parsed_record": record, "record": record, "edited_fields": [],
                           "issues": [i.__dict__ for i in issues if i.field != "candidate_id"]})
        self.db.update("resume_documents", doc["id"], status="needs_review", candidate_id=cid,
                       display_name=record["profile"]["anonymized_name"], title=record["profile"]["current_title"],
                       n_pages=extracted.n_pages, n_warnings=len(warnings), contact_key=key,
                       possible_duplicate_of=possible, extraction_path=str(path),
                       record_json=json.dumps(record, ensure_ascii=False, default=str), updated_at=now())

    # ------------------------------------------------------------------ documents
    def _doc(self, doc_id: str, owner: str) -> dict:
        row = self.db.one("SELECT * FROM resume_documents WHERE id=? AND owner=?", (doc_id, owner))
        if not row:
            raise AppError(404, "document_not_found", "Resume document not found.")
        return row

    def list_documents(self, batch_id: str, owner: str, status: str | None, q: str | None,
                       limit: int, offset: int) -> dict:
        self._batch(batch_id, owner)
        where, params = ["batch_id=?"], [batch_id]
        if status:
            if status == "processed":
                where.append("status IN ('needs_review','approved','rejected')")
            else:
                where.append("status=?")
                params.append(status)
        if q:
            where.append("(filename LIKE ? OR display_name LIKE ? OR title LIKE ?)")
            params += [f"%{q}%"] * 3
        sql_where = " AND ".join(where)
        total = self.db.one(f"SELECT COUNT(*) AS n FROM resume_documents WHERE {sql_where}", params)["n"]
        cols = ", ".join(DOC_COLUMNS)
        rows = self.db.query(f"SELECT {cols} FROM resume_documents WHERE {sql_where} "
                             "ORDER BY created_at, id LIMIT ? OFFSET ?", [*params, limit, offset])
        return {"total": total, "items": rows}

    def _load(self, doc: dict) -> dict:
        if not doc["extraction_path"] or not Path(doc["extraction_path"]).exists():
            return {}
        return json.loads(Path(doc["extraction_path"]).read_text(encoding="utf-8"))

    def get_document(self, doc_id: str, owner: str) -> dict:
        doc = self._doc(doc_id, owner)
        out = {k: doc[k] for k in DOC_COLUMNS}
        out.update(self._load(doc))
        out["text_pages"] = (out.get("extraction") or {}).pop("text_pages", [])
        for ref in ("duplicate_of", "possible_duplicate_of"):
            if doc[ref]:
                other = self.db.one("SELECT id, filename, batch_id FROM resume_documents WHERE id=? AND owner=?",
                                    (doc[ref], owner))
                out[ref + "_doc"] = other
        out["has_original"] = bool(doc["stored_path"] and Path(doc["stored_path"]).exists())
        return out

    def by_candidate(self, candidate_id: str, owner: str) -> dict:
        row = self.db.one("SELECT id, batch_id FROM resume_documents WHERE owner=? AND candidate_id=?",
                          (owner, candidate_id))
        if not row:
            raise AppError(404, "document_not_found", "No resume in your uploads produced this candidate.")
        return row

    def update_record(self, doc_id: str, owner: str, record: dict) -> dict:
        """Replace the candidate record with a recruiter-corrected version.

        The corrected record is validated with the same ``Normalizer`` as any
        dataset row. The candidate id cannot change. Fields that differ from
        the parsed record are listed in ``edited_fields`` (shown as *edited*)."""
        doc = self._doc(doc_id, owner)
        if doc["status"] not in REVIEWABLE:
            raise AppError(409, "not_reviewable", f"A {doc['status']} document cannot be edited.")
        data = self._load(doc)
        record = dict(record)
        record["candidate_id"] = doc["candidate_id"]
        record.setdefault("redrob_signals", {})
        normalized, issues = Normalizer().normalize(record)
        errors = [i for i in issues if i.level == "error"]
        if normalized is None or errors:
            raise AppError(422, "invalid_record", "; ".join(i.message for i in errors) or "Invalid record.")
        parsed = _flatten(data["parsed_record"])
        new = _flatten(normalized)
        data["record"] = normalized
        data["edited_fields"] = sorted(k for k in set(parsed) | set(new) if parsed.get(k) != new.get(k))
        data["issues"] = [i.__dict__ for i in issues if i.field != "candidate_id"]
        _write_json(Path(doc["extraction_path"]), data)
        self.db.update("resume_documents", doc_id, edited=1 if data["edited_fields"] else 0,
                       record_json=json.dumps(normalized, ensure_ascii=False, default=str),
                       display_name=normalized["profile"]["anonymized_name"],
                       title=normalized["profile"]["current_title"], updated_at=now())
        return self.get_document(doc_id, owner)

    def set_status(self, doc_id: str, owner: str, status: str) -> dict:
        doc = self._doc(doc_id, owner)
        if doc["status"] not in REVIEWABLE:
            raise AppError(409, "not_reviewable", f"A {doc['status']} document cannot be {status}.")
        self.db.update("resume_documents", doc_id, status=status, updated_at=now())
        return self.get_document(doc_id, owner)

    def approve_clean(self, batch_id: str, owner: str) -> dict:
        self._batch(batch_id, owner)
        n = self.db.execute("UPDATE resume_documents SET status='approved', updated_at=? WHERE batch_id=? "
                            "AND status='needs_review' AND n_warnings=0 AND possible_duplicate_of IS NULL",
                            (now(), batch_id))
        return {"approved": n}

    def original(self, doc_id: str, owner: str) -> tuple[Path, str, str]:
        doc = self._doc(doc_id, owner)
        if not doc["stored_path"] or not Path(doc["stored_path"]).exists():
            raise AppError(404, "original_missing", "The original file is not stored for this document.")
        media = "application/pdf" if doc["kind"] == "pdf" else \
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return Path(doc["stored_path"]), media, doc["filename"]

    # ------------------------------------------------------------------ publish
    def publish(self, batch_id: str, owner: str, name: str | None) -> dict:
        """Write approved records to JSONL and register them as a dataset; the
        existing indexing job then makes them rankable."""
        batch = self._batch(batch_id, owner)
        n_approved = self.db.one("SELECT COUNT(*) AS n FROM resume_documents WHERE batch_id=? AND status='approved'",
                                 (batch_id,))["n"]
        if not n_approved:
            raise AppError(409, "nothing_approved", "Approve at least one resume before publishing.")
        fd, tmp_name = tempfile.mkstemp(dir=self.s.uploads_dir, suffix=".jsonl.tmp")
        dest = self.s.uploads_dir / f"{new_id()}.jsonl"
        written = 0
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                # Streamed from SQLite in pages: memory stays flat for any batch size.
                last = ""
                while True:
                    rows = self.db.query("SELECT id, record_json FROM resume_documents WHERE batch_id=? AND "
                                         "status='approved' AND id>? ORDER BY id LIMIT 1000", (batch_id, last))
                    if not rows:
                        break
                    for row in rows:
                        out.write(row["record_json"] + "\n")
                    written += len(rows)
                    last = rows[-1]["id"]
            os.replace(tmp_name, dest)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        ds = self.datasets.register_file(owner, (name or f"Resumes - {batch['name']}") + ".jsonl", dest)
        self.db.update("resume_batches", batch_id, last_dataset_id=ds["id"], updated_at=now())
        self.db.log_activity(owner, "resumes", f"Published {written:,} approved resume(s) as dataset "
                                               f"'{ds['name']}'", batch_id)
        return {"dataset": ds, "published": written}
