"""Ranking runs: create, persist, query, explain, compare.

A run = (dataset, JobSpec, shortlist size). The full pool is scored in a
background job; the *result table* (the shortlist plus every candidate held
out of eligibility, with display columns) is written to
``artifacts/runs/<run_id>.parquet``. Filtering, sorting and pagination are
served from that table, so the browser only ever receives one page.

Explanations need the full scored pool (requirement evidence pointers). Pools
are kept in a small LRU; after a restart the pool is recomputed from the
stored JobSpec, which is deterministic, so explanations stay identical.
"""
from __future__ import annotations

import json
import threading
from collections import OrderedDict
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import Settings
from app.core.errors import AppError
from app.database.db import Database, dumps, new_id, now
from app.services.datasets import DatasetService
from app.services.jobs import JobContext, JobManager
from engine.explanations.explain import explain_candidate
from engine.jd.spec import JobSpec
from engine.preprocessing.store import DatasetIndex
from engine.ranking.scorer import COMPONENTS, ScoredPool, score_pool

MET_THRESHOLD = 0.65
SORTABLE = {"rank", "overall", "requirements", "role_fit", "semantic", "experience", "engagement", "logistics",
            "years_experience", "mandatory_coverage", "evidence_completeness", "name", "title", "company"}
DISPLAY_COLS = ["name", "title", "company", "industry", "location", "city", "country", "years_experience",
                "fields_of_study", "highest_degree", "skills", "n_assessments", "sig_notice_period_days",
                "sig_recruiter_response_rate", "sig_last_active_date", "sig_open_to_work_flag",
                "sig_preferred_work_mode"]


class _LRU:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.items: OrderedDict[str, Any] = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key: str):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
        return None

    def put(self, key: str, value: Any) -> None:
        with self.lock:
            self.items[key] = value
            self.items.move_to_end(key)
            while len(self.items) > self.capacity:
                self.items.popitem(last=False)


class RunService:
    def __init__(self, settings: Settings, db: Database, jobs: JobManager, datasets: DatasetService):
        self.s = settings
        self.db = db
        self.jobs = jobs
        self.datasets = datasets
        self.pools = _LRU(2)
        self.tables = _LRU(6)
        self._recompute_lock = threading.Lock()

    # ---- creation ----------------------------------------------------------
    def create(self, owner: str, dataset_id: str, spec: JobSpec, shortlist_size: int | None, name: str | None) -> dict:
        ds = self.datasets.get(dataset_id, owner)
        if ds["status"] != "ready":
            raise AppError(409, "dataset_not_ready", "The dataset is still being indexed.")
        if shortlist_size is not None and shortlist_size < 1:
            raise AppError(422, "invalid_size", "Shortlist size must be at least 1 (or omitted for all eligible).")
        run_id = new_id()
        row = {"id": run_id, "owner": owner, "dataset_id": dataset_id,
               "name": (name or f"{spec.title} - {ds['name']}")[:160], "jd_title": spec.title[:160],
               "spec_json": spec.model_dump_json(), "shortlist_size": shortlist_size, "status": "queued",
               "created_at": now()}
        self.db.insert("runs", row)

        def work(ctx: JobContext) -> None:
            self.db.update("runs", run_id, status="running")
            ctx.progress(0.05, "Loading dataset index")
            ix = self.datasets.index(ds)
            ctx.check()
            ctx.progress(0.2, f"Scoring {ix.n:,} candidates")
            pool = score_pool(ix, spec)
            ctx.check()
            ctx.progress(0.8, "Saving results")
            table = self._result_table(ix, pool, spec, shortlist_size)
            table.to_parquet(self.s.runs_dir / f"{run_id}.parquet", index=False)
            self.pools.put(run_id, (pool, ix, spec))
            self.tables.put(run_id, table)
            summary = self._summary(pool, table)
            self.db.update("runs", run_id, status="ready", n_candidates=ix.n, n_eligible=pool.context["n_eligible"],
                           n_results=int(table["eligible"].sum()), summary_json=dumps(summary), finished_at=now())
            self.db.log_activity(owner, "run", f"Ranked {ix.n:,} candidates for '{spec.title}'", run_id)

        job_id = self.jobs.submit(
            "rank", run_id, owner, work,
            on_error=lambda msg: self.db.update("runs", run_id, status="failed", error=msg, finished_at=now()),
            on_cancel=lambda: self.db.update("runs", run_id, status="cancelled", finished_at=now()))
        self.db.update("runs", run_id, job_id=job_id)
        return self.get(run_id, owner)

    def _result_table(self, ix: DatasetIndex, pool: ScoredPool, spec: JobSpec, size: int | None) -> pd.DataFrame:
        t = pool.table
        keep = t[t["eligible"]] if size is None else t[t["eligible"]].head(size)
        held = t[~t["eligible"]]
        res = pd.concat([keep, held], ignore_index=True)
        cand = ix.candidates.set_index("idx")
        disp = cand.loc[res["idx"], DISPLAY_COLS].reset_index(drop=True)
        res = pd.concat([res.reset_index(drop=True), disp], axis=1)

        jd_skills = {s.lower() for r in spec.requirements for s in r.skills}
        res["relevant_skills"] = [
            "|".join(s for s in (sk or "").split("|") if s and s.lower() in jd_skills) for sk in res["skills"]]
        sk = ix.skills
        rel = sk[sk["skill"].str.lower().isin(jd_skills) & sk["assessed"].notna()]
        mean_assessed = rel.groupby("idx")["assessed"].mean()
        res["assessment_mean"] = res["idx"].map(mean_assessed).astype("float32")
        flags = ix.integrity
        sev = flags.groupby("idx")["code"].agg(lambda s: "|".join(sorted(set(s))))
        res["flag_codes"] = res["idx"].map(sev).fillna("")
        res.loc[res["uncorroborated_skills"], "flag_codes"] = (
            res.loc[res["uncorroborated_skills"], "flag_codes"].str.strip("|") + "|uncorroborated_skill_claims"
        ).str.strip("|")
        mand = [r.id for r in pool.requirements if r.importance == "mandatory"]
        res["mandatory_met"] = (res[[f"req_{m}" for m in mand]] >= MET_THRESHOLD).sum(axis=1).astype("int16") \
            if mand else 0
        res["mandatory_total"] = len(mand)
        return res

    def _summary(self, pool: ScoredPool, table: pd.DataFrame) -> dict:
        elig = pool.table[pool.table["eligible"]]["overall"].to_numpy()
        hist, edges = np.histogram(elig, bins=20, range=(0, 1))
        short = table[table["eligible"]]
        return {
            "context": {k: v for k, v in pool.context.items() if k not in ("role_relevance", "best_semantic_role_row")},
            "score_histogram": {"counts": hist.tolist(), "edges": [round(e, 3) for e in edges.tolist()]},
            "shortlist_component_means": {c: round(float(short[c].mean()), 4) for c in COMPONENTS} if len(short) else {},
            "n_held_for_review": int((~table["eligible"]).sum()),
            "requirements": [{"id": r.id, "label": r.label, "importance": r.importance,
                              "met_in_shortlist": int((short[f"req_{r.id}"] >= MET_THRESHOLD).sum()) if len(short) else 0}
                             for r in pool.requirements],
        }

    # ---- reading -------------------------------------------------------------
    def list(self, owner: str, limit: int = 50) -> list[dict]:
        rows = self.db.query(
            "SELECT r.id, r.name, r.jd_title, r.status, r.shortlist_size, r.n_candidates, r.n_eligible, r.n_results, "
            "r.created_at, r.finished_at, r.dataset_id, d.name AS dataset_name FROM runs r "
            "JOIN datasets d ON d.id = r.dataset_id WHERE r.owner = ? ORDER BY r.created_at DESC LIMIT ?",
            (owner, limit))
        return rows

    def get(self, run_id: str, owner: str) -> dict:
        row = self.db.one("SELECT r.*, d.name AS dataset_name FROM runs r JOIN datasets d ON d.id = r.dataset_id "
                          "WHERE r.id = ? AND r.owner = ?", (run_id, owner))
        if not row:
            raise AppError(404, "run_not_found", "Run not found.")
        row["spec"] = json.loads(row.pop("spec_json"))
        row["summary"] = json.loads(row["summary_json"]) if row.get("summary_json") else None
        row.pop("summary_json", None)
        row["job"] = self.jobs.get(row["job_id"]) if row.get("job_id") else None
        return row

    def delete(self, run_id: str, owner: str) -> None:
        run = self.get(run_id, owner)
        if run["job"] and run["job"]["status"] in ("queued", "running"):
            self.jobs.cancel(run["job"]["id"])
        self.db.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        (self.s.runs_dir / f"{run_id}.parquet").unlink(missing_ok=True)

    def table(self, run_id: str, owner: str) -> pd.DataFrame:
        run = self.get(run_id, owner)
        if run["status"] != "ready":
            raise AppError(409, "run_not_ready", f"Run is {run['status']}.")
        t = self.tables.get(run_id)
        if t is None:
            path = self.s.runs_dir / f"{run_id}.parquet"
            if not path.exists():
                raise AppError(410, "results_missing", "Result files for this run are missing.")
            t = pd.read_parquet(path)
            self.tables.put(run_id, t)
        return t

    def pool(self, run_id: str, owner: str) -> tuple[ScoredPool, DatasetIndex, JobSpec]:
        cached = self.pools.get(run_id)
        if cached:
            return cached
        run = self.get(run_id, owner)
        with self._recompute_lock:
            cached = self.pools.get(run_id)
            if cached:
                return cached
            ds = self.datasets.get(run["dataset_id"], owner)
            ix = self.datasets.index(ds)
            spec = JobSpec.model_validate(run["spec"])
            entry = (score_pool(ix, spec), ix, spec)
            self.pools.put(run_id, entry)
            return entry

    # ---- results query ---------------------------------------------------
    def query(self, run_id: str, owner: str, *, page: int = 1, page_size: int = 50, sort: str = "rank",
              order: str = "asc", q: str = "", view: str = "shortlist", min_score: float | None = None,
              max_score: float | None = None, min_years: float | None = None, max_years: float | None = None,
              countries: list[str] | None = None, cities: list[str] | None = None,
              branches: list[str] | None = None, skills: list[str] | None = None,
              flags: str | None = None, min_mandatory: int | None = None) -> dict:
        t = self.table(run_id, owner)
        df = t[t["eligible"]] if view == "shortlist" else t[~t["eligible"]] if view == "held" else t
        if q:
            ql = q.lower()
            hay = (df["name"].fillna("") + " " + df["title"].fillna("") + " " + df["company"].fillna("") + " "
                   + df["candidate_id"] + " " + df["skills"].fillna("")).str.lower()
            df = df[hay.str.contains(ql, regex=False)]
        if min_score is not None:
            df = df[df["overall"] >= min_score]
        if max_score is not None:
            df = df[df["overall"] <= max_score]
        if min_years is not None:
            df = df[df["years_experience"] >= min_years]
        if max_years is not None:
            df = df[df["years_experience"] <= max_years]
        if countries:
            df = df[df["country"].isin(countries)]
        if cities:
            df = df[df["city"].isin(cities)]
        if branches:
            pat = "|".join(map(_re_escape, branches))
            df = df[df["fields_of_study"].fillna("").str.contains(pat, regex=True)]
        if skills:
            low = df["skills"].fillna("").str.lower().str.split("|")
            want = {s.lower() for s in skills}
            df = df[low.map(lambda xs: want.issubset(set(xs)))]
        if flags == "none":
            df = df[df["flag_codes"] == ""]
        elif flags == "any":
            df = df[df["flag_codes"] != ""]
        elif flags == "critical":
            df = df[df["critical_flag"]]
        elif flags == "warning":
            df = df[df["warning_flags"] > 0]
        if min_mandatory is not None:
            df = df[df["mandatory_met"] >= min_mandatory]
        if sort not in SORTABLE:
            raise AppError(422, "invalid_sort", f"Cannot sort by '{sort}'.")
        asc = order == "asc"
        if sort == "rank":
            key = df["rank"].where(df["rank"] > 0, np.iinfo(np.int32).max)
            df = df.assign(_k=key).sort_values(["_k", "candidate_id"], ascending=[asc, True]).drop(columns="_k")
        else:
            df = df.sort_values([sort, "candidate_id"], ascending=[asc, True], na_position="last")
        total = len(df)
        page_size = max(1, min(page_size, 200))
        page = max(1, page)
        chunk = df.iloc[(page - 1) * page_size: page * page_size]
        return {"total": total, "page": page, "page_size": page_size, "items": [_row_json(r) for r in chunk.itertuples()]}

    def facets(self, run_id: str, owner: str, view: str = "shortlist") -> dict:
        t = self.table(run_id, owner)
        df = t[t["eligible"]] if view == "shortlist" else t
        def counts(s: pd.Series, k: int = 30):
            vc = s.value_counts().head(k)
            return [{"value": str(i), "count": int(c)} for i, c in vc.items()]
        branches = df["fields_of_study"].fillna("").str.split("; ").explode()
        skills = df["relevant_skills"].fillna("").str.split("|").explode()
        return {
            "countries": counts(df["country"]),
            "cities": counts(df["city"], 40),
            "branches": counts(branches[branches != ""]),
            "skills": counts(skills[skills != ""], 40),
            "flags": {"none": int((df["flag_codes"] == "").sum()), "any": int((df["flag_codes"] != "").sum()),
                      "critical": int(df["critical_flag"].sum()), "warning": int((df["warning_flags"] > 0).sum())},
            "years": {"min": _num(df["years_experience"].min()), "max": _num(df["years_experience"].max())},
            "score": {"min": _num(df["overall"].min()), "max": _num(df["overall"].max())},
            "held_for_review": int((~t["eligible"]).sum()),
        }

    def explain(self, run_id: str, owner: str, candidate_id: str) -> dict:
        pool, ix, spec = self.pool(run_id, owner)
        try:
            return _clean(explain_candidate(ix, pool, spec, candidate_id))
        except KeyError as exc:
            raise AppError(404, "candidate_not_found", "Candidate not found in this run.") from exc

    def compare(self, run_id: str, owner: str, candidate_ids: list[str]) -> dict:
        if not 2 <= len(candidate_ids) <= 6:
            raise AppError(422, "compare_count", "Select between 2 and 6 candidates to compare.")
        items = [self.explain(run_id, owner, cid) for cid in dict.fromkeys(candidate_ids)]
        reqs = [{"id": r["id"], "label": r["label"], "importance": r["importance"],
                 "values": [next(x for x in it["requirements"] if x["id"] == r["id"])["coverage"] for it in items]}
                for r in items[0]["requirements"]]
        comps = [{"id": c["id"], "label": c["label"], "values": [next(x for x in it["components"] if x["id"] == c["id"])["value"]
                                                                  for it in items]} for c in items[0]["components"]]
        return {"candidates": items, "requirements": reqs, "components": comps}


def _re_escape(s: str) -> str:
    import re
    return re.escape(s)


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else round(v, 4)


def _row_json(r) -> dict:
    d = r._asdict()
    d.pop("Index", None)
    out = {}
    for k, v in d.items():
        if isinstance(v, (np.floating, float)):
            out[k] = None if np.isnan(v) else round(float(v), 4)
        elif isinstance(v, (np.integer,)):
            out[k] = int(v)
        elif isinstance(v, (np.bool_,)):
            out[k] = bool(v)
        elif v is pd.NA or v is None:
            out[k] = None
        else:
            out[k] = v
    out["skills"] = [s for s in (out.get("skills") or "").split("|") if s]
    out["relevant_skills"] = [s for s in (out.get("relevant_skills") or "").split("|") if s]
    out["flag_codes"] = [s for s in (out.get("flag_codes") or "").split("|") if s]
    out["requirement_coverage"] = {k[4:]: out.pop(k) for k in list(out) if k.startswith("req_")}
    out["constraints_triggered"] = [k[2:] for k in list(out) if k.startswith("c_") and out.pop(k)]
    for k in [k for k in out if k.startswith(("eng_", "log_", "exp_"))]:
        out.pop(k)
    return out


def _clean(obj):
    """Make explanation output JSON-safe (NaN -> None, numpy -> python)."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj
