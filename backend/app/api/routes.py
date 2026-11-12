"""HTTP API. Thin layer: validate input, call a service, return JSON.

All routes live under /api. Every route except /api/health requires the
X-Session-Id header (see core/security.py).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import Response

from app.core.errors import AppError
from app.core.security import session_owner
from app.schemas.api import (CompareRequest, CreateRunRequest, ExportRequest, ImportPathRequest, ParseJDRequest,
                             ShortlistCreate, ShortlistItem)
from app.services import exports
from engine import __version__
from engine.jd.documents import DocumentError, extract_text
from engine.jd.parser import parse_job_description
from engine.jd.spec import JobSpec
from engine.taxonomy import load_taxonomy

router = APIRouter(prefix="/api")
Owner = Annotated[str, Depends(session_owner)]
JOBS_DIR_NAME = "jobs"


def services(request: Request):
    return request.app.state.services


# ---- health / meta ----------------------------------------------------------
@router.get("/health")
def health(request: Request):
    s = services(request)
    return {"status": "ok", "version": __version__,
            "semantic_model": s.semantic_model_available, "frontend_built": s.settings.frontend_dist.exists()}


@router.get("/dashboard")
def dashboard(request: Request, owner: Owner):
    s = services(request)
    datasets = [_dataset_json(s, d) for d in s.datasets.visible(owner)]
    runs = s.runs.list(owner, limit=8)
    activity = s.db.query("SELECT kind, message, ref_id, created_at FROM activity WHERE owner = ? OR owner IS NULL "
                          "ORDER BY created_at DESC LIMIT 12", (owner,))
    ready = [d for d in datasets if d["status"] == "ready"]
    return {
        "datasets": datasets,
        "recent_runs": runs,
        "activity": activity,
        "totals": {"datasets": len(datasets), "ready_datasets": len(ready),
                   "candidates": sum(d["n_candidates"] or 0 for d in ready),
                   "runs": s.db.one("SELECT COUNT(*) AS n FROM runs WHERE owner = ?", (owner,))["n"],
                   "shortlists": s.db.one("SELECT COUNT(*) AS n FROM shortlists WHERE owner = ?", (owner,))["n"]},
    }


@router.get("/taxonomy/concepts")
def concepts(owner: Owner):
    tax = load_taxonomy()
    return [{"id": c.id, "label": c.label, "category": c.category, "skills": list(c.skills),
             "phrases": list(c.phrases), "semantic": c.semantic, "signal": c.signal} for c in tax.concepts.values()]


# ---- datasets -------------------------------------------------------------
def _dataset_json(s, d: dict) -> dict:
    out = {k: d[k] for k in ("id", "name", "source_kind", "size_bytes", "status", "n_candidates", "error",
                             "created_at", "updated_at", "fingerprint")}
    out["shared"] = d["owner"] is None
    job = s.datasets.latest_job(d["id"])
    out["job"] = job
    return out


@router.get("/datasets")
def list_datasets(request: Request, owner: Owner):
    s = services(request)
    return [_dataset_json(s, d) for d in s.datasets.visible(owner)]


@router.post("/datasets/upload", status_code=201)
def upload_dataset(request: Request, owner: Owner, file: UploadFile = File(...)):
    s = services(request)
    return _dataset_json(s, s.datasets.save_upload(owner, file.filename or "upload", file.file))


@router.post("/datasets/import-path", status_code=201)
def import_dataset(request: Request, owner: Owner, body: ImportPathRequest):
    s = services(request)
    return _dataset_json(s, s.datasets.import_path(owner, body.path))


@router.get("/datasets/import-dirs")
def import_dirs(request: Request, owner: Owner):
    return [str(p) for p in services(request).settings.import_dirs]


@router.get("/datasets/{dataset_id}")
def get_dataset(request: Request, owner: Owner, dataset_id: str):
    s = services(request)
    d = s.datasets.get(dataset_id, owner)
    out = _dataset_json(s, d)
    if d["status"] == "ready":
        ix = s.datasets.index(d)
        out["quality"] = ix.quality
        out["meta"] = ix.meta
    return out


@router.post("/datasets/{dataset_id}/reindex")
def reindex(request: Request, owner: Owner, dataset_id: str):
    s = services(request)
    d = s.datasets.get(dataset_id, owner)
    if d["status"] == "indexing":
        raise AppError(409, "already_indexing", "Indexing is already in progress.")
    s.datasets.start_index(d, owner)
    return _dataset_json(s, s.datasets.get(dataset_id, owner))


@router.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(request: Request, owner: Owner, dataset_id: str):
    services(request).datasets.delete(dataset_id, owner)
    return Response(status_code=204)


# ---- jobs -----------------------------------------------------------------
@router.get("/jobs/{job_id}")
def get_job(request: Request, owner: Owner, job_id: str):
    job = services(request).jobs.get(job_id)
    if not job or (job["owner"] not in (None, owner)):
        raise AppError(404, "job_not_found", "Job not found.")
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, owner: Owner, job_id: str):
    s = services(request)
    job = s.jobs.get(job_id)
    if not job or job["owner"] != owner:
        raise AppError(404, "job_not_found", "Job not found.")
    if job["status"] not in ("queued", "running"):
        raise AppError(409, "job_finished", f"Job already {job['status']}.")
    s.jobs.cancel(job_id)
    return {"cancelling": True}


# ---- job descriptions -------------------------------------------------------
def _known_locations(s, owner: str, dataset_id: str | None) -> list[str]:
    if not dataset_id:
        return []
    d = s.datasets.get(dataset_id, owner)
    if d["status"] != "ready":
        return []
    return s.datasets.index(d).candidates["location"].dropna().unique().tolist()


@router.post("/jd/parse")
def parse_jd(request: Request, owner: Owner, body: ParseJDRequest):
    s = services(request)
    spec = parse_job_description(body.text, known_locations=_known_locations(s, owner, body.dataset_id))
    return spec.model_dump()


@router.post("/jd/upload")
async def upload_jd(request: Request, owner: Owner, file: UploadFile = File(...),
                    dataset_id: str | None = Query(default=None)):
    s = services(request)
    data = await file.read(s.settings.max_jd_upload_mb * 1024 * 1024 + 1)
    if len(data) > s.settings.max_jd_upload_mb * 1024 * 1024:
        raise AppError(413, "file_too_large", f"Job descriptions are limited to {s.settings.max_jd_upload_mb} MB.")
    try:
        text = extract_text(file.filename or "jd.txt", data)
    except DocumentError as exc:
        raise AppError(415, "unsupported_document", str(exc)) from exc
    if len(text.strip()) < 20:
        raise AppError(422, "empty_document", "No readable text was found in the document.")
    spec = parse_job_description(text[:60_000], known_locations=_known_locations(s, owner, dataset_id))
    return {"text": text[:60_000], "spec": spec.model_dump()}


@router.get("/jd/presets")
def jd_presets(request: Request, owner: Owner):
    from engine.jd import parser as _p  # noqa: F401  (ensures package import path)
    from pathlib import Path
    root = Path(__file__).resolve().parents[3] / "engine" / "resources" / JOBS_DIR_NAME
    return [{"id": p.stem, "title": p.read_text(encoding="utf-8").splitlines()[0][:120],
             "text": p.read_text(encoding="utf-8")} for p in sorted(root.glob("*.txt"))]


# ---- runs -----------------------------------------------------------------
@router.get("/runs")
def list_runs(request: Request, owner: Owner, limit: int = Query(50, ge=1, le=500)):
    return services(request).runs.list(owner, limit)


@router.post("/runs", status_code=201)
def create_run(request: Request, owner: Owner, body: CreateRunRequest):
    return services(request).runs.create(owner, body.dataset_id, body.spec, body.shortlist_size, body.name)


@router.get("/runs/{run_id}")
def get_run(request: Request, owner: Owner, run_id: str):
    return services(request).runs.get(run_id, owner)


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(request: Request, owner: Owner, run_id: str):
    services(request).runs.delete(run_id, owner)
    return Response(status_code=204)


@router.get("/runs/{run_id}/results")
def run_results(request: Request, owner: Owner, run_id: str,
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                sort: str = "rank", order: str = Query("asc", pattern="^(asc|desc)$"),
                q: str = Query("", max_length=200), view: str = Query("shortlist", pattern="^(shortlist|held|all)$"),
                min_score: float | None = None, max_score: float | None = None,
                min_years: float | None = None, max_years: float | None = None,
                countries: str | None = None, cities: str | None = None, branches: str | None = None,
                skills: str | None = None, flags: str | None = Query(None, pattern="^(none|any|critical|warning)$"),
                min_mandatory: int | None = Query(None, ge=0)):
    split = lambda v: [x for x in v.split(",") if x] if v else None  # noqa: E731
    return services(request).runs.query(
        run_id, owner, page=page, page_size=page_size, sort=sort, order=order, q=q, view=view,
        min_score=min_score, max_score=max_score, min_years=min_years, max_years=max_years,
        countries=split(countries), cities=split(cities), branches=split(branches), skills=split(skills),
        flags=flags, min_mandatory=min_mandatory)


@router.get("/runs/{run_id}/facets")
def run_facets(request: Request, owner: Owner, run_id: str, view: str = Query("shortlist", pattern="^(shortlist|all)$")):
    return services(request).runs.facets(run_id, owner, view)


@router.get("/runs/{run_id}/candidates/{candidate_id}")
def candidate_detail(request: Request, owner: Owner, run_id: str, candidate_id: str):
    return services(request).runs.explain(run_id, owner, candidate_id)


@router.post("/runs/{run_id}/compare")
def compare(request: Request, owner: Owner, run_id: str, body: CompareRequest):
    return services(request).runs.compare(run_id, owner, body.candidate_ids)


@router.post("/runs/{run_id}/export")
def export_run(request: Request, owner: Owner, run_id: str, body: ExportRequest):
    data, media, name = exports.export(services(request).runs, run_id, owner, body.format, body.scope,
                                       body.candidate_ids, body.include_explanations)
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/runs/{run_id}/export/competition")
def export_competition(request: Request, owner: Owner, run_id: str):
    data, problems = exports.competition_export(services(request).runs, run_id, owner)
    if problems:
        raise AppError(422, "competition_invalid", "Validation failed: " + "; ".join(problems[:5]))
    return Response(data, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="submission_{run_id[:8]}.csv"'})


@router.post("/runs/rerun/{run_id}", status_code=201)
def rerun(request: Request, owner: Owner, run_id: str):
    s = services(request)
    run = s.runs.get(run_id, owner)
    return s.runs.create(owner, run["dataset_id"], JobSpec.model_validate(run["spec"]), run["shortlist_size"],
                         run["name"] + " (re-run)")


# ---- shortlists -------------------------------------------------------------
@router.get("/shortlists")
def list_shortlists(request: Request, owner: Owner):
    return services(request).shortlists.list(owner)


@router.post("/shortlists", status_code=201)
def create_shortlist(request: Request, owner: Owner, body: ShortlistCreate):
    return services(request).shortlists.create(owner, body.run_id, body.name, body.candidate_ids)


@router.get("/shortlists/{sid}")
def get_shortlist(request: Request, owner: Owner, sid: str):
    return services(request).shortlists.get(sid, owner)


@router.post("/shortlists/{sid}/items")
def add_item(request: Request, owner: Owner, sid: str, body: ShortlistItem):
    return services(request).shortlists.add(sid, owner, body.candidate_id, body.note)


@router.delete("/shortlists/{sid}/items/{candidate_id}")
def remove_item(request: Request, owner: Owner, sid: str, candidate_id: str):
    return services(request).shortlists.remove(sid, owner, candidate_id)


@router.delete("/shortlists/{sid}", status_code=204)
def delete_shortlist(request: Request, owner: Owner, sid: str):
    services(request).shortlists.delete(sid, owner)
    return Response(status_code=204)
