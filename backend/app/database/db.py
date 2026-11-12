"""SQLite persistence (standard-library ``sqlite3``; no ORM).

Why no ORM: the schema is small and the queries are simple; plain SQL keeps
every statement visible and easy to debug. WAL mode lets the API read while
a background job writes. Each thread gets its own connection.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS datasets (
    id            TEXT PRIMARY KEY,
    owner         TEXT,                      -- NULL = shared library dataset
    name          TEXT NOT NULL,
    source_kind   TEXT NOT NULL CHECK (source_kind IN ('upload', 'path', 'library')),
    source_path   TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    mtime         REAL,
    fingerprint   TEXT,
    status        TEXT NOT NULL CHECK (status IN ('pending', 'indexing', 'ready', 'failed')),
    n_candidates  INTEGER,
    index_dir     TEXT,
    error         TEXT,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_datasets_owner ON datasets(owner);

CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    owner        TEXT,
    kind         TEXT NOT NULL CHECK (kind IN ('index', 'rank')),
    target_id    TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    progress     REAL NOT NULL DEFAULT 0,
    message      TEXT,
    error        TEXT,
    created_at   REAL NOT NULL,
    started_at   REAL,
    finished_at  REAL
);
CREATE INDEX IF NOT EXISTS ix_jobs_target ON jobs(target_id);

CREATE TABLE IF NOT EXISTS runs (
    id             TEXT PRIMARY KEY,
    owner          TEXT NOT NULL,
    dataset_id     TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    jd_title       TEXT NOT NULL,
    spec_json      TEXT NOT NULL,
    shortlist_size INTEGER,                  -- NULL = all eligible candidates
    status         TEXT NOT NULL CHECK (status IN ('queued', 'running', 'ready', 'failed', 'cancelled')),
    job_id         TEXT,
    n_candidates   INTEGER,
    n_eligible     INTEGER,
    n_results      INTEGER,
    summary_json   TEXT,
    error          TEXT,
    created_at     REAL NOT NULL,
    finished_at    REAL
);
CREATE INDEX IF NOT EXISTS ix_runs_owner ON runs(owner, created_at);

CREATE TABLE IF NOT EXISTS shortlists (
    id          TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    run_id      TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_shortlists_owner ON shortlists(owner);

CREATE TABLE IF NOT EXISTS shortlist_items (
    shortlist_id  TEXT NOT NULL REFERENCES shortlists(id) ON DELETE CASCADE,
    candidate_id  TEXT NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    added_at      REAL NOT NULL,
    PRIMARY KEY (shortlist_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner       TEXT,
    kind        TEXT NOT NULL,
    message     TEXT NOT NULL,
    ref_id      TEXT,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_activity_owner ON activity(owner, created_at);
"""


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> float:
    return time.time()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._local = threading.local()
        self.write_lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.write_lock:
            c = self.conn
            c.executescript(SCHEMA)
            c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            c.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return c

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        r = self.conn.execute(sql, tuple(params)).fetchone()
        return dict(r) if r else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self.write_lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur.rowcount

    def insert(self, table: str, row: dict) -> None:
        cols = ", ".join(row)
        qs = ", ".join("?" for _ in row)
        self.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", row.values())

    def update(self, table: str, id_: str, **fields: Any) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*fields.values(), id_])

    def log_activity(self, owner: str | None, kind: str, message: str, ref_id: str | None = None) -> None:
        self.insert("activity", {"owner": owner, "kind": kind, "message": message[:300], "ref_id": ref_id,
                                 "created_at": now()})


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)
