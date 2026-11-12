"""FastAPI application factory.

    cd backend && uvicorn app.main:app --port 8000

If ``frontend/dist`` exists (``npm run build``), the built single-page app is
served from the same origin, so production needs only one process.
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # make the engine package importable
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.api.routes import router  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.errors import install_error_handlers  # noqa: E402
from app.database.db import Database  # noqa: E402
from app.services.datasets import DatasetService, IndexCache  # noqa: E402
from app.services.jobs import JobManager  # noqa: E402
from app.services.resumes import ResumeService  # noqa: E402
from app.services.runs import RunService  # noqa: E402
from app.services.shortlists import ShortlistService  # noqa: E402

log = logging.getLogger("talentsignal")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                                "base-uri 'self'; form-action 'self'"),
}


@dataclass
class Services:
    settings: Settings
    db: Database
    jobs: JobManager
    datasets: DatasetService
    runs: RunService
    shortlists: ShortlistService
    semantic_model_available: bool
    resumes: ResumeService


def build_services(settings: Settings) -> Services:
    settings.ensure_dirs()
    db = Database(settings.db_path)
    jobs = JobManager(db, settings.job_workers)
    datasets = DatasetService(settings, db, jobs, IndexCache())
    runs = RunService(settings, db, jobs, datasets)
    from engine.retrieval.embeddings import default_model_dir
    return Services(settings, db, jobs, datasets, runs, ShortlistService(db, runs),
                    (default_model_dir() / "config.json").exists(), ResumeService(settings, db, jobs, datasets))


def create_app(settings: Settings | None = None, register_library: bool = True) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services = build_services(settings)
        app.state.services = services
        if register_library:
            services.datasets.register_library()
        log.info("TalentSignal ready (semantic model available: %s)", services.semantic_model_available)
        yield
        services.jobs.shutdown()

    app = FastAPI(title="TalentSignal API", version="1.0.0", lifespan=lifespan)
    install_error_handlers(app)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                       allow_headers=["*"], expose_headers=["Content-Disposition"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    app.include_router(router)

    dist = settings.frontend_dist
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse({"error": {"code": "not_found", "message": "Unknown API route."}}, 404)
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    return app


app = create_app()
