"""Dataset registration, upload handling and index builds."""
from __future__ import annotations

import logging
import shutil
import threading
from collections import OrderedDict
from pathlib import Path
from typing import BinaryIO

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import safe_display_name
from app.database.db import Database, new_id, now
from app.services.jobs import JobCancelled, JobContext, JobManager
from engine.ingestion.fingerprint import file_fingerprint
from engine.ingestion.readers import SUPPORTED_EXTENSIONS, UnsupportedFormat, detect_format
from engine.preprocessing.index import Cancelled, build_index
from engine.preprocessing.store import DatasetIndex, IndexNotFound

log = logging.getLogger("talentsignal.datasets")
COPY_CHUNK = 4 * 1024 * 1024


class IndexCache:
    """Keeps the most recently used dataset indexes in memory (LRU)."""

    def __init__(self, capacity: int = 3):
        self.capacity = capacity
        self._items: OrderedDict[str, DatasetIndex] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, index_dir: str) -> DatasetIndex:
        with self._lock:
            if index_dir in self._items:
                self._items.move_to_end(index_dir)
                return self._items[index_dir]
        ix = DatasetIndex(index_dir)
        with self._lock:
            self._items[index_dir] = ix
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)
        return ix

    def drop(self, index_dir: str) -> None:
        with self._lock:
            self._items.pop(index_dir, None)


class DatasetService:
    def __init__(self, settings: Settings, db: Database, jobs: JobManager, cache: IndexCache):
        self.s = settings
        self.db = db
        self.jobs = jobs
        self.cache = cache

    # ---- queries ---------------------------------------------------------
    def visible(self, owner: str) -> list[dict]:
        return self.db.query("SELECT * FROM datasets WHERE owner IS NULL OR owner = ? ORDER BY created_at DESC",
                             (owner,))

    def get(self, dataset_id: str, owner: str) -> dict:
        row = self.db.one("SELECT * FROM datasets WHERE id = ? AND (owner IS NULL OR owner = ?)", (dataset_id, owner))
        if not row:
            raise AppError(404, "dataset_not_found", "Dataset not found.")
        return row

    def index(self, dataset: dict) -> DatasetIndex:
        if dataset["status"] != "ready" or not dataset["index_dir"]:
            raise AppError(409, "dataset_not_ready", "The dataset index is not ready yet.")
        try:
            return self.cache.get(dataset["index_dir"])
        except IndexNotFound as exc:
            raise AppError(409, "index_missing", f"Index files are missing or outdated: {exc}") from exc

    # ---- registration ----------------------------------------------------
    def _create(self, owner: str | None, name: str, kind: str, path: Path) -> dict:
        st = path.stat()
        row = {"id": new_id(), "owner": owner, "name": name, "source_kind": kind, "source_path": str(path),
               "size_bytes": st.st_size, "mtime": st.st_mtime, "status": "pending", "created_at": now(),
               "updated_at": now()}
        self.db.insert("datasets", row)
        self.db.log_activity(owner, "dataset", f"Dataset '{name}' registered", row["id"])
        return row

    def save_upload(self, owner: str, filename: str, stream: BinaryIO) -> dict:
        name = safe_display_name(filename)
        ext = Path(name).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise AppError(415, "unsupported_format",
                           f"Unsupported file type '{ext or '(none)'}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}")
        limit = self.s.max_upload_mb * 1024 * 1024
        dest = self.s.uploads_dir / f"{new_id()}{ext}"  # server-chosen name; user input never reaches the path
        written = 0
        try:
            with open(dest, "wb") as out:
                while chunk := stream.read(COPY_CHUNK):
                    written += len(chunk)
                    if written > limit:
                        raise AppError(413, "file_too_large", f"File exceeds the {self.s.max_upload_mb} MB limit.")
                    out.write(chunk)
        except AppError:
            dest.unlink(missing_ok=True)
            raise
        if written == 0:
            dest.unlink(missing_ok=True)
            raise AppError(400, "empty_file", "The uploaded file is empty.")
        row = self._create(owner, name, "upload", dest)
        self.start_index(row, owner)
        return self.get(row["id"], owner)

    def register_file(self, owner: str, name: str, path: Path) -> dict:
        """Register a server-generated file in ``uploads_dir`` (e.g. published
        resume candidates) as an uploaded dataset and start indexing it."""
        if not path.resolve().is_relative_to(self.s.uploads_dir.resolve()):
            raise AppError(400, "invalid_path", "Generated datasets must live in the uploads directory.")
        row = self._create(owner, safe_display_name(name), "upload", path)
        self.start_index(row, owner)
        return self.get(row["id"], owner)

    def import_path(self, owner: str, raw_path: str) -> dict:
        try:
            path = Path(raw_path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise AppError(404, "path_not_found", "The file does not exist on the server.") from exc
        if not any(path.is_relative_to(d) for d in self.s.import_dirs):
            raise AppError(403, "path_not_allowed",
                           "Imports are only allowed from configured server directories: "
                           + "; ".join(str(d) for d in self.s.import_dirs))
        if not path.is_file():
            raise AppError(400, "not_a_file", "The path is not a file.")
        try:
            detect_format(path)
        except UnsupportedFormat as exc:
            raise AppError(415, "unsupported_format", str(exc)) from exc
        row = self._create(owner, safe_display_name(path.name), "path", path)
        self.start_index(row, owner)
        return self.get(row["id"], owner)

    def register_library(self) -> None:
        """Register configured shared datasets at start-up (idempotent)."""
        for path in self.s.library_datasets:
            if not path.exists():
                continue
            st = path.stat()
            existing = self.db.one("SELECT * FROM datasets WHERE source_kind='library' AND source_path=?", (str(path),))
            if existing and existing["size_bytes"] == st.st_size and existing["mtime"] == st.st_mtime \
                    and existing["status"] in ("ready", "indexing"):
                continue
            if existing:
                self.db.execute("DELETE FROM datasets WHERE id=?", (existing["id"],))
            row = self._create(None, path.name, "library", path)
            self.start_index(row, None)

    # ---- indexing --------------------------------------------------------
    def start_index(self, row: dict, owner: str | None) -> str:
        ds_id = row["id"]

        def work(ctx: JobContext) -> None:
            self.db.update("datasets", ds_id, status="indexing", updated_at=now(), error=None)
            ctx.progress(0.01, "Fingerprinting file")
            fp = file_fingerprint(row["source_path"])
            index_dir = self.s.indexes_dir / fp
            try:
                ix = DatasetIndex(index_dir)  # identical file already indexed: reuse it
                ctx.progress(1.0, "Reused existing index")
            except IndexNotFound:
                tmp = index_dir.with_name(index_dir.name + ".building")
                shutil.rmtree(tmp, ignore_errors=True)
                try:
                    build_index(row["source_path"], tmp, progress=ctx.progress, should_cancel=ctx.cancelled)
                except Cancelled as exc:
                    shutil.rmtree(tmp, ignore_errors=True)
                    raise JobCancelled() from exc
                except Exception:
                    shutil.rmtree(tmp, ignore_errors=True)
                    raise
                shutil.rmtree(index_dir, ignore_errors=True)
                tmp.rename(index_dir)
                ix = DatasetIndex(index_dir)
            self.db.update("datasets", ds_id, status="ready", fingerprint=fp, index_dir=str(index_dir),
                           n_candidates=ix.n, updated_at=now())
            self.db.log_activity(owner, "dataset", f"Dataset '{row['name']}' indexed ({ix.n:,} candidates)", ds_id)

        def failed(msg: str) -> None:
            self.db.update("datasets", ds_id, status="failed", error=msg, updated_at=now())

        def cancelled() -> None:
            self.db.update("datasets", ds_id, status="failed", error="Indexing was cancelled.", updated_at=now())

        return self.jobs.submit("index", ds_id, owner, work, on_error=failed, on_cancel=cancelled)

    def latest_job(self, dataset_id: str) -> dict | None:
        return self.db.one("SELECT * FROM jobs WHERE target_id=? ORDER BY created_at DESC LIMIT 1", (dataset_id,))

    # ---- deletion --------------------------------------------------------
    def delete(self, dataset_id: str, owner: str) -> None:
        row = self.get(dataset_id, owner)
        if row["owner"] is None:
            raise AppError(403, "read_only", "Library datasets cannot be deleted from the app.")
        job = self.latest_job(dataset_id)
        if job and job["status"] in ("queued", "running"):
            self.jobs.cancel(job["id"])
        for run in self.db.query("SELECT id FROM runs WHERE dataset_id=?", (dataset_id,)):
            (self.s.runs_dir / f"{run['id']}.parquet").unlink(missing_ok=True)
        self.db.execute("DELETE FROM datasets WHERE id=?", (dataset_id,))
        if row["source_kind"] == "upload":
            Path(row["source_path"]).unlink(missing_ok=True)
        if row["index_dir"] and not self.db.one("SELECT 1 FROM datasets WHERE index_dir=?", (row["index_dir"],)):
            self.cache.drop(row["index_dir"])
            shutil.rmtree(row["index_dir"], ignore_errors=True)
        self.db.log_activity(owner, "dataset", f"Dataset '{row['name']}' deleted", dataset_id)
