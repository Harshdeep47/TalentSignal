"""Synthetic adversarial dataset for robustness tests.

Starting from real records, builds a small candidate file containing:
  * ``base``       -- a sample of real candidates (strong and weak);
  * ``stuffer``    -- non-technical profiles given every JD skill at
                      "expert" with long usage AND perfect platform assessments
                      (the strongest keyword-stuffing attack the schema allows);
  * ``impossible`` -- strong profiles made internally impossible (several
                      expert skills with 0 months of use);
  * ``sparse``     -- copies of strong profiles with all optional evidence
                      removed (no assessments, no GitHub, no offer history),
                      to measure how much missing *optional* data costs;
  * ``twin``       -- copies of strong profiles with identical text but much
                      weaker behavioural signals (look-alike differentiation).

Synthetic ids use the prefix SYN_ so they can never be confused with real ones.
"""
from __future__ import annotations

import copy
import random
from pathlib import Path

import orjson

from engine.jd.spec import JobSpec
from engine.preprocessing.store import DatasetIndex


def build_adversarial_file(ix: DatasetIndex, strong_ids: list[str], weak_ids: list[str], spec: JobSpec,
                           out_path: Path, n_each: int = 30, seed: int = 7) -> dict[str, list[str]]:
    rnd = random.Random(seed)
    groups: dict[str, list[str]] = {"base": [], "stuffer": [], "impossible": [], "sparse": [], "twin": []}
    jd_skills = sorted({s for r in spec.requirements for s in r.skills})
    strong = [ix.record_by_id(c) for c in strong_ids]
    weak = [ix.record_by_id(c) for c in weak_ids]
    lines = []

    for rec in strong + weak:
        groups["base"].append(rec["candidate_id"])
        lines.append(rec)

    non_tech = [r for r in weak if r["profile"]["current_title"] in
                {"HR Manager", "Marketing Manager", "Sales Executive", "Content Writer", "Accountant", "Business Analyst"}]
    for k in range(n_each):
        src = copy.deepcopy(rnd.choice(non_tech or weak))
        src["candidate_id"] = f"SYN_STUFF_{k:03d}"
        src["skills"] = [{"name": s, "proficiency": "expert", "endorsements": 50, "duration_months": 60}
                         for s in jd_skills]
        src["redrob_signals"]["skill_assessment_scores"] = {s: 95 for s in jd_skills[:12]}
        src["profile"]["headline"] = "AI Engineer | RAG, Embeddings, Vector Search, Ranking, LLMs"
        groups["stuffer"].append(src["candidate_id"])
        lines.append(src)

    for k in range(n_each):
        base = strong[k % len(strong)]
        src = copy.deepcopy(base)
        src["candidate_id"] = f"SYN_IMPOSSIBLE_{k:03d}"
        for s in src["skills"][:4]:
            s["proficiency"], s["duration_months"] = "expert", 0
        groups["impossible"].append(src["candidate_id"])
        lines.append(src)

        sp = copy.deepcopy(base)
        sp["candidate_id"] = f"SYN_SPARSE_{k:03d}"
        sig = sp["redrob_signals"]
        sig["skill_assessment_scores"] = {}
        sig["github_activity_score"] = None
        sig["offer_acceptance_rate"] = None
        groups["sparse"].append(sp["candidate_id"])
        lines.append(sp)

        tw = copy.deepcopy(base)
        tw["candidate_id"] = f"SYN_TWIN_{k:03d}"
        sig = tw["redrob_signals"]
        sig["recruiter_response_rate"] = 0.05
        sig["last_active_date"] = "2025-10-01"
        sig["open_to_work_flag"] = False
        sig["interview_completion_rate"] = 0.3
        groups["twin"].append(tw["candidate_id"])
        lines.append(tw)

    with open(out_path, "wb") as f:
        for rec in lines:
            f.write(orjson.dumps(rec) + b"\n")
    return groups
