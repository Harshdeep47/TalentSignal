"""Application settings, read from environment variables (no secrets in code).

Every setting has a safe local default so `uvicorn app.main:app` works out of
the box. Override with environment variables, e.g.:

    TALENTSIGNAL_DATA_DIR=/srv/talentsignal/data
    TALENTSIGNAL_MAX_UPLOAD_MB=1024
    TALENTSIGNAL_IMPORT_DIRS=/srv/datasets;/mnt/shared
    TALENTSIGNAL_LIBRARY_DATASETS=/srv/datasets/candidates.jsonl
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _paths(value: str | None, default: list[Path]) -> list[Path]:
    if not value:
        return default
    return [Path(p).expanduser().resolve() for p in value.split(os.pathsep) if p.strip()]


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get(
        "TALENTSIGNAL_DATA_DIR", PROJECT_ROOT / "data")).resolve())
    artifacts_dir: Path = field(default_factory=lambda: Path(os.environ.get(
        "TALENTSIGNAL_ARTIFACTS_DIR", PROJECT_ROOT / "artifacts")).resolve())
    max_upload_mb: int = field(default_factory=lambda: int(os.environ.get("TALENTSIGNAL_MAX_UPLOAD_MB", "2048")))
    max_jd_upload_mb: int = 5
    # Server-side directories from which datasets may be imported by path
    # (avoids pushing hundreds of MB through the browser).
    import_dirs: list[Path] = field(default_factory=lambda: _paths(
        os.environ.get("TALENTSIGNAL_IMPORT_DIRS"), [(PROJECT_ROOT.parent / "reference material").resolve()]))
    # Datasets registered at startup as shared, read-only library datasets.
    library_datasets: list[Path] = field(default_factory=lambda: _paths(
        os.environ.get("TALENTSIGNAL_LIBRARY_DATASETS"),
        [p for p in [(PROJECT_ROOT.parent / "reference material" / "candidates.jsonl").resolve()] if p.exists()]))
    cors_origins: list[str] = field(default_factory=lambda: os.environ.get(
        "TALENTSIGNAL_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","))
    job_workers: int = field(default_factory=lambda: int(os.environ.get("TALENTSIGNAL_JOB_WORKERS", "2")))
    frontend_dist: Path = field(default_factory=lambda: PROJECT_ROOT / "frontend" / "dist")
    log_level: str = field(default_factory=lambda: os.environ.get("TALENTSIGNAL_LOG_LEVEL", "INFO"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "talentsignal.sqlite3"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def indexes_dir(self) -> Path:
        return self.artifacts_dir / "indexes"

    @property
    def runs_dir(self) -> Path:
        return self.artifacts_dir / "runs"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.uploads_dir, self.indexes_dir, self.runs_dir):
            d.mkdir(parents=True, exist_ok=True)
