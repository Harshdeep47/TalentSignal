"""Exports of a run's results: CSV, XLSX, JSON, JSONL, Parquet, PDF report,
and the competition-format CSV.

Text cells in CSV/XLSX are protected against spreadsheet formula injection
(a candidate-provided value such as ``=HYPERLINK(...)`` is prefixed with ``'``).
"""
from __future__ import annotations

import csv
import io
import json
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.errors import AppError
from app.core.security import csv_safe
from app.services.runs import RunService
from engine.ranking.competition import competition_rows, validate_submission, write_submission

EXPORT_COLUMNS = ["rank", "candidate_id", "name", "overall", "title", "company", "location", "country",
                  "years_experience", "fields_of_study", "relevant_skills", "mandatory_met", "mandatory_total",
                  "requirements", "role_fit", "semantic", "lexical", "experience", "engagement", "logistics",
                  "constraint_factor", "evidence_completeness", "assessment_mean", "flag_codes", "eligible",
                  "ineligible_reason"]
MAX_EXPLAINED_ROWS = 500
FORMATS = {"csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
           "json": "application/json", "jsonl": "application/x-ndjson", "parquet": "application/octet-stream",
           "pdf": "application/pdf"}


def _frame(runs: RunService, run_id: str, owner: str, scope: str, candidate_ids: list[str] | None,
           with_summaries: bool) -> pd.DataFrame:
    t = runs.table(run_id, owner)
    if candidate_ids is not None:
        df = t[t["candidate_id"].isin(candidate_ids)]
    elif scope == "all":
        df = t
    else:
        df = t[t["eligible"]]
    df = df.sort_values(["eligible", "rank"], ascending=[False, True])
    out = df[[c for c in EXPORT_COLUMNS if c in df.columns]].copy()
    out["rank"] = out["rank"].where(out["rank"] > 0, None)
    if with_summaries:
        if len(out) > MAX_EXPLAINED_ROWS:
            raise AppError(422, "too_many_rows",
                           f"Explanations can be included for at most {MAX_EXPLAINED_ROWS} rows; "
                           "narrow the export or omit explanations.")
        out["explanation"] = [runs.explain(run_id, owner, c)["summary"] for c in out["candidate_id"]]
    return out


def export(runs: RunService, run_id: str, owner: str, fmt: str, scope: str = "shortlist",
           candidate_ids: list[str] | None = None, with_summaries: bool = False) -> tuple[bytes, str, str]:
    if fmt not in FORMATS:
        raise AppError(422, "invalid_format", f"Format must be one of: {', '.join(FORMATS)}.")
    run = runs.get(run_id, owner)
    df = _frame(runs, run_id, owner, scope, candidate_ids, with_summaries)
    stem = f"talentsignal_{run_id[:8]}"
    if fmt == "csv":
        buf = io.StringIO()
        df.map(csv_safe).to_csv(buf, index=False)
        data = buf.getvalue().encode("utf-8-sig")
    elif fmt == "xlsx":
        data = _xlsx(df, run)
    elif fmt == "json":
        data = json.dumps({"run": _run_meta(run), "candidates": json.loads(df.to_json(orient="records"))},
                          indent=1).encode("utf-8")
    elif fmt == "jsonl":
        data = df.to_json(orient="records", lines=True).encode("utf-8")
    elif fmt == "parquet":
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        data = buf.getvalue()
    else:
        data = _pdf(runs, run, owner, df)
    return data, FORMATS[fmt], f"{stem}.{fmt}"


def _run_meta(run: dict) -> dict:
    return {"id": run["id"], "name": run["name"], "job_title": run["jd_title"], "dataset": run["dataset_name"],
            "created_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(run["created_at"])),
            "candidates_scored": run["n_candidates"], "eligible": run["n_eligible"],
            "shortlist_size": run["shortlist_size"] or "all eligible"}


def _xlsx(df: pd.DataFrame, run: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Ranking"
    ws.append(list(df.columns))
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F2A44")
    for row in df.itertuples(index=False):
        ws.append([csv_safe(_xl(v)) for v in row])
    ws.freeze_panes = "A2"
    info = wb.create_sheet("Run")
    for k, v in _run_meta(run).items():
        info.append([k, str(v)])
    info.append([])
    info.append(["note", "Scores are evidence-based relevance estimates for decision support, not hiring "
                         "probabilities. Review candidates individually."])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _xl(v):
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if v is pd.NA:
        return None
    return v


def _pdf(runs: RunService, run: dict, owner: str, df: pd.DataFrame) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"TalentSignal - {run['jd_title']}")
    st = getSampleStyleSheet()
    small = st["BodyText"].clone("small", fontSize=8, leading=10)
    story = [Paragraph(escape(f"TalentSignal shortlist report: {run['jd_title']}"), st["Title"]),
             Paragraph(escape(" | ".join(f"{k}: {v}" for k, v in _run_meta(run).items())), small), Spacer(1, 6),
             Paragraph("Scores are evidence-based relevance estimates to support - not replace - recruiter "
                       "judgement. They are not probabilities of hiring success.", small), Spacer(1, 8)]
    top = df[df["eligible"]].head(50)
    rows = [["#", "Candidate", "Role", "Score", "Must-haves", "Flags"]]
    for r in top.itertuples():
        rows.append([str(int(r.rank)) if r.rank else "-", Paragraph(escape(f"{r.name} ({r.candidate_id})"), small),
                     Paragraph(escape(f"{r.title} - {r.company}"), small), f"{r.overall:.3f}",
                     f"{r.mandatory_met}/{r.mandatory_total}", Paragraph(escape(str(r.flag_codes or "")), small)])
    table = Table(rows, colWidths=[10 * mm, 50 * mm, 62 * mm, 16 * mm, 18 * mm, 26 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2A44")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9CED8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F2EC")])]))
    story += [table, Spacer(1, 10), Paragraph("Top candidates - evidence summaries", st["Heading2"])]
    for cid in top["candidate_id"].head(15):
        e = runs.explain(run["id"], owner, cid)
        story.append(Paragraph(escape(f"#{e['rank']} {cid}: {e['summary']}"), small))
        story.append(Spacer(1, 3))
    doc.build(story)
    return buf.getvalue()


def competition_export(runs: RunService, run_id: str, owner: str) -> tuple[bytes, list[str]]:
    """Exactly-100-row competition CSV, validated before it is returned."""
    pool, ix, spec = runs.pool(run_id, owner)
    if pool.context["n_eligible"] < 100:
        raise AppError(422, "not_enough_candidates", "Competition format needs at least 100 eligible candidates.")
    rows = competition_rows(ix, pool, spec)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "submission.csv"
        write_submission(rows, p)
        problems = validate_submission(p, set(ix.candidates["candidate_id"]))
        data = p.read_bytes()
    return data, problems
