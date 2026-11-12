"""Generate the end-to-end worked ranking example used in the learning books.

Runs the REAL TalentSignal engine (parser, index build, scorer, explanations)
on one short job description and three hypothetical candidates, and writes
every intermediate number to worked_example.json. The books quote these
numbers, so they always match the implementation.

    .venv/Scripts/python docs/learning/build/worked_example.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from engine.explanations.explain import explain_candidate  # noqa: E402
from engine.features.evidence import skill_row_strength  # noqa: E402
from engine.jd.parser import parse_job_description  # noqa: E402
from engine.preprocessing.index import build_index  # noqa: E402
from engine.preprocessing.store import DatasetIndex  # noqa: E402
from engine.ranking.scorer import COMPONENTS, score_pool  # noqa: E402
from factories import candidate, write_jsonl  # noqa: E402
import numpy as np  # noqa: E402

JD = """Search Engineer
Company: Example Commerce (product company)
Location: Pune, India (Hybrid) | Open to relocation within India
Experience Required: 4-8 years

What you'll do
- Own the ranking of our product search results.
- Run offline evaluation and A/B tests before shipping ranking changes.

Must have:
- Production experience with Elasticsearch or another search engine
- Experience building ranking or recommendation systems
- Strong Python

Nice to have:
- Learning-to-rank models such as LightGBM or XGBoost

Notice period: we prefer sub-30-day notice; we can buy out up to 30 days.
"""

A_DESC = ("Owned the ranking layer of our e-commerce search: moved from hand-tuned BM25 boosts in Elasticsearch to a "
          "learning-to-rank model trained with LightGBM. Ran offline NDCG evaluation and A/B tests; shipped to "
          "production serving 20M queries a month. Wrote the Python ranking service.")
B_DESC = "Enterprise sales of cloud software solutions into the mid-market segment; carried a revenue quota."
C_DESC = ("Designed how our marketplace decides which listings each shopper sees first. Rebuilt the ordering logic "
          "so the most relevant items surface for every query, measured the impact with controlled experiments, "
          "and kept the service fast for millions of daily visitors.")

CANDIDATES = [
    candidate("CAND_9000001", title="Search Engineer", desc=A_DESC, years=6.0, company="ShopFast",
              location="Pune, Maharashtra", name="Asha Rao",
              skills=[("Elasticsearch", "advanced", 48), ("Python", "expert", 72),
                      ("Learning to Rank", "advanced", 30), ("Ranking Systems", "advanced", 36)],
              signals={"skill_assessment_scores": {"Elasticsearch": 84}, "recruiter_response_rate": 0.8,
                       "notice_period_days": 30, "last_active_date": "2026-05-20"}),
    candidate("CAND_9000002", title="Sales Executive", desc=B_DESC, years=6.0, company="CloudCo",
              location="Bangalore, Karnataka", name="Ravi Menon", industry="Software",
              skills=[(s, "expert", 60) for s in ("Elasticsearch", "Python", "Learning to Rank", "Ranking Systems",
                                                   "Recommendation Systems", "Search Infrastructure", "BM25")],
              signals={"recruiter_response_rate": 0.9, "notice_period_days": 15, "last_active_date": "2026-05-25"}),
    candidate("CAND_9000003", title="Senior Software Engineer", desc=C_DESC, years=7.0, company="MarketHub",
              location="Hyderabad, Telangana", name="Meera Iyer",
              skills=[("Python", "advanced", 60), ("Java", "advanced", 48)],
              signals={"recruiter_response_rate": 0.5, "notice_period_days": 90, "last_active_date": "2026-02-01",
                       "github_activity_score": None, "offer_acceptance_rate": None}),
]


def main() -> None:
    out: dict = {}
    spec = parse_job_description(JD)
    out["jd"] = JD
    out["spec"] = {
        "title": spec.title, "role_families": spec.role_families, "seniority_level": spec.seniority_level,
        "requirements": [{"id": r.id, "label": r.label, "importance": r.importance, "weight": r.weight,
                          "skills": r.skills[:6], "source_text": r.source_text} for r in spec.requirements],
        "experience": spec.experience.model_dump(), "location": spec.location.model_dump(),
        "notice": spec.notice.model_dump(), "constraints": [c.model_dump() for c in spec.constraints],
        "weights": spec.weights.normalized(), "notes": spec.extraction_notes,
    }
    with tempfile.TemporaryDirectory() as td:
        src = write_jsonl(CANDIDATES, Path(td) / "c.jsonl")
        build_index(src, Path(td) / "ix", embed=True)
        ix = DatasetIndex(Path(td) / "ix")
        pool = score_pool(ix, spec)
        t = pool.table.set_index("candidate_id")
        out["context"] = {k: v for k, v in pool.context.items() if k in ("as_of_date", "weights_used", "notes",
                                                                         "focus_bounds", "semantic_available")}
        cands = {}
        for c in CANDIDATES:
            cid = c["candidate_id"]
            row = t.loc[cid]
            i = int(row["idx"])
            reqs = {}
            for r in pool.requirements:
                ev = pool.evidence[r.id]
                reqs[r.id] = {"skill": round(float(ev.skill[i]), 4), "text": round(float(ev.text[i]), 4),
                              "signal": round(float(ev.signal[i]), 4), "coverage": round(float(ev.coverage[i]), 4)}
            e = explain_candidate(ix, pool, spec, cid)
            cands[cid] = {
                "name": c["profile"]["anonymized_name"], "title": c["profile"]["current_title"],
                "rank": int(row["rank"]), "overall": round(float(row["overall"]), 4),
                "components": {k: round(float(row[k]), 4) for k in COMPONENTS},
                "constraint_factor": round(float(row["constraint_factor"]), 4),
                "title_relevance": round(float(row["title_relevance"]), 4),
                "career_relevance": round(float(row["career_relevance"]), 4),
                "relevant_years": round(float(row["relevant_years"]), 3),
                "mandatory_coverage": round(float(row["mandatory_coverage"]), 4),
                "uncorroborated": bool(row["uncorroborated_skills"]),
                "eng": {k[4:]: (None if np.isnan(v) else round(float(v), 4)) for k, v in row.items() if k.startswith("eng_")},
                "log": {k[4:]: (None if np.isnan(v) else round(float(v), 4)) for k, v in row.items() if k.startswith("log_")},
                "exp": {k[4:]: (None if np.isnan(v) else round(float(v), 4)) for k, v in row.items() if k.startswith("exp_")},
                "requirements": reqs,
                "summary": e["summary"], "concerns": e["concerns"], "missing": e["missing_information"],
                "flags": [f["code"] for f in e["flags"]],
            }
        out["candidates"] = cands
    # A few hand-checkable formula values
    out["skill_strength_examples"] = {
        "advanced_48m_assessed_84": float(skill_row_strength(np.array([0.75]), np.array([48.0]), np.array([84.0]))[0]),
        "expert_60m_unassessed": float(skill_row_strength(np.array([1.0]), np.array([60.0]), np.array([np.nan]))[0]),
        "expert_0m_unassessed": float(skill_row_strength(np.array([1.0]), np.array([0.0]), np.array([np.nan]))[0]),
    }
    (Path(__file__).parent / "worked_example.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
