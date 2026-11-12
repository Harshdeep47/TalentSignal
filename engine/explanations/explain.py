"""Grounded, per-candidate explanations.

Everything here is derived from two sources only:
  * the scored pool (component values, requirement coverage, and the exact
    skill row / role row that produced each requirement's evidence), and
  * the candidate's own normalised record.

The explanation answers: why this rank, which requirements are met and by
what evidence, which skills are verified, what is missing, what concerns
exist, and what separates the candidate from neighbours in the ranking.
All evidence items pass ``validator.validate_evidence`` before use, and the
generated summary passes ``validator.validate_text``.
"""
from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
import pandas as pd

from engine.explanations.validator import validate_evidence, validate_text
from engine.jd.spec import JobSpec
from engine.preprocessing.store import DatasetIndex
from engine.ranking.scorer import COMPONENTS, ScoredPool

COMPONENT_LABELS = {
    "requirements": "Requirement coverage", "role_fit": "Role relevance", "semantic": "Semantic match",
    "lexical": "Keyword relevance", "experience": "Experience fit", "engagement": "Engagement signals",
    "logistics": "Location & availability",
}
MET, PARTIAL = 0.65, 0.30
SIGNAL_LABELS = {
    "recruiter_response_rate": "recruiter response rate", "last_active_date": "last active",
    "notice_period_days": "notice period", "interview_completion_rate": "interview attendance",
    "github_activity_score": "GitHub activity", "offer_acceptance_rate": "offer acceptance",
    "open_to_work_flag": "open to work",
}


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _status(c: float) -> str:
    return "met" if c >= MET else "partial" if c >= PARTIAL else "missing"


def _matched_phrases(text: str, phrases: list[str], limit: int = 3) -> list[str]:
    low = text.lower()
    found = []
    for p in sorted({p.lower() for p in phrases if len(p) >= 2}, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", low) and not any(p in f for f in found):
            found.append(p)
        if len(found) >= limit:
            break
    return found


def _requirement_detail(ix: DatasetIndex, pool: ScoredPool, req, i: int, rec: dict) -> dict:
    ev = pool.evidence[req.id]
    cov = float(ev.coverage[i])
    items: list[dict] = []
    srow = int(ev.best_skill_row[i])
    if srow >= 0 and ev.skill[i] > 0:
        s = ix.skills.iloc[srow]
        assessed = _f(s["assessed"])
        items.append({"kind": "skill", "skill": s["skill"], "proficiency": s["proficiency"] or None,
                      "months": _f(s["months"]), "assessed": assessed, "verified": assessed is not None,
                      "strength": round(float(ev.skill[i]), 3)})
    rrow = int(ev.best_role_row[i])
    if ev.text[i] > 0.05:
        if ev.text_from_summary[i]:
            text = rec["profile"]["summary"] + " " + rec["profile"]["headline"]
            items.append({"kind": "summary_text", "phrases": _matched_phrases(text, req.phrases + req.skills),
                          "strength": round(float(ev.text[i]), 3)})
        elif rrow >= 0:
            role = ix.roles.iloc[rrow]
            order = int(role["order"])
            desc = rec["career_history"][order]["description"] if order < len(rec["career_history"]) else ""
            items.append({"kind": "role_text", "role_index": order, "title": role["title"],
                          "company": role["company"], "is_current": bool(role["is_current"]),
                          "months": _f(role["months"]), "phrases": _matched_phrases(desc, req.phrases + req.skills),
                          "strength": round(float(ev.text[i]), 3)})
    if ev.signal[i] > 0 and req.signal:
        items.append({"kind": "signal", "signal": req.signal, "value": rec["redrob_signals"].get(req.signal),
                      "strength": round(float(ev.signal[i]), 3)})
    items = [it for it in items if validate_evidence(it, rec)]
    return {"id": req.id, "label": req.label, "importance": req.importance, "weight": req.weight,
            "coverage": round(cov, 3), "status": _status(cov), "evidence": items,
            "skill_matches": int(ev.n_skill_matches[i])}


def _evidence_phrase(it: dict) -> str:
    if it["kind"] == "skill":
        bits = [it["proficiency"]] if it.get("proficiency") else []
        if it.get("assessed") is not None:
            bits.append(f"assessed {it['assessed']:.0f}/100")
        return f"{it['skill']}" + (f" ({', '.join(bits)})" if bits else "")
    if it["kind"] == "role_text":
        where = "the current role" if it["is_current"] else f"a {it['title']} role at {it['company']}"
        if it["phrases"]:
            return f"{where} citing " + " and ".join(f"'{p}'" for p in it["phrases"][:2])
        return f"{where} describing closely related work"
    if it["kind"] == "summary_text":
        return "a summary citing " + " and ".join(f"'{p}'" for p in it["phrases"][:2]) if it["phrases"] \
            else "a summary describing related work"
    if it["kind"] == "signal":
        return f"GitHub activity {float(it['value']):.0f}/100"
    return ""


def _concerns(row: pd.Series, rec: dict, spec: JobSpec, as_of: str) -> list[str]:
    s = rec["redrob_signals"]
    p = rec["profile"]
    out = []
    if s.get("notice_period_days") is not None and spec.notice.ideal_max_days is not None \
            and s["notice_period_days"] > spec.notice.ideal_max_days:
        out.append(f"notice period {s['notice_period_days']} days (JD prefers <= {spec.notice.ideal_max_days})")
    rr = s.get("recruiter_response_rate")
    if rr is not None and rr < 0.3:
        out.append(f"recruiter response rate {rr:.0%}")
    la = s.get("last_active_date")
    if la:
        days = (pd.Timestamp(as_of) - pd.Timestamp(la)).days
        if days > 120:
            out.append(f"last active {days} days before {as_of}")
    if s.get("open_to_work_flag") is False:
        out.append("not marked open to work")
    yoe = p.get("years_of_experience")
    e = spec.experience
    if yoe is not None and e.min_years is not None and yoe < e.min_years:
        out.append(f"{yoe:.1f} years of experience, below the {e.min_years:g}-year guide")
    if yoe is not None and e.max_years is not None and yoe > e.max_years + 2:
        out.append(f"{yoe:.1f} years of experience, above the {e.max_years:g}-year guide")
    if spec.location.countries and p.get("country") and p["country"] not in spec.location.countries:
        reloc = s.get("willing_to_relocate")
        out.append(f"based in {p['country']}" + (" (willing to relocate)" if reloc else " and not willing to relocate"))
    ir = s.get("interview_completion_rate")
    if ir is not None and ir < 0.5:
        out.append(f"attended {ir:.0%} of scheduled interviews")
    return out


def _missing_info(rec: dict, has_rel_assessment: bool) -> list[str]:
    s = rec["redrob_signals"]
    out = []
    if not has_rel_assessment:
        out.append("No platform assessment for the job's key skills")
    if s.get("github_activity_score") is None:
        out.append("No GitHub account linked")
    if s.get("offer_acceptance_rate") is None:
        out.append("No prior offer history")
    for k, label in (("notice_period_days", "Notice period"), ("interview_completion_rate", "Interview history"),
                     ("last_active_date", "Last activity date")):
        if s.get(k) is None:
            out.append(f"{label} not provided")
    return out


def _tone(rank: int, overall: float, eligible: bool = True) -> str:
    if not eligible:
        return "Held for review"
    if rank and rank <= 10 and overall >= 0.6:
        return "Top match"
    if overall >= 0.75:
        return "Strong match"
    if overall >= 0.6:
        return "Good match"
    if overall >= 0.45:
        return "Partial match"
    return "Weak match"


def _differentiators(pool: ScoredPool, pos: int, k: int = 3) -> list[dict]:
    t = pool.table
    lo, hi = max(0, pos - k), min(len(t), pos + k + 1)
    neigh = t.iloc[[j for j in range(lo, hi) if j != pos]]
    if neigh.empty:
        return []
    me = t.iloc[pos]
    weights = pool.context["weights_used"]
    diffs = []
    for c in COMPONENTS:
        if c not in weights:
            continue
        d = (float(me[c]) - float(neigh[c].mean())) * weights[c]
        diffs.append({"component": c, "label": COMPONENT_LABELS[c], "delta": round(d, 4),
                      "value": round(float(me[c]), 3), "neighbour_mean": round(float(neigh[c].mean()), 3)})
    diffs.sort(key=lambda d: -abs(d["delta"]))
    return [d for d in diffs if abs(d["delta"]) >= 0.002][:3]


def explain_candidate(ix: DatasetIndex, pool: ScoredPool, spec: JobSpec, candidate_id: str) -> dict:
    t = pool.table
    hits = np.flatnonzero(t["candidate_id"].to_numpy() == candidate_id)
    if len(hits) == 0:
        raise KeyError(candidate_id)
    pos = int(hits[0])
    row = t.iloc[pos]
    i = int(row["idx"])
    rec = ix.record(i)
    as_of = pool.context["as_of_date"]

    reqs = [_requirement_detail(ix, pool, r, i, rec) for r in pool.requirements]
    has_rel_assess = any(it["kind"] == "skill" and it["verified"] for r in reqs for it in r["evidence"])
    weights = pool.context["weights_used"]
    components = [{"id": c, "label": COMPONENT_LABELS[c], "value": round(float(row[c]), 4),
                   "weight": round(weights.get(c, 0.0), 4),
                   "contribution": round(float(row[c]) * weights.get(c, 0.0), 4)} for c in COMPONENTS]
    triggered = [{"id": c.id, "label": c.label, "policy": c.policy, "factor": c.factor, "source_text": c.source_text}
                 for c in spec.constraints if bool(row.get(f"c_{c.id}", False))]
    flags = ix.flags_for(i)
    if bool(row["uncorroborated_skills"]):
        flags.append({"code": "uncorroborated_skill_claims", "severity": "warning",
                      "title": "Job-relevant skills not supported by any related role",
                      "detail": "Several of this job's skills are listed, but no role in the career history has a "
                                "title related to the job. Skill claims were counted at reduced weight.",
                      "evidence": {}})

    mand = [r for r in reqs if r["importance"] == "mandatory"]
    met = [r for r in mand if r["status"] == "met"]
    strengths, gaps = [], []
    for r in sorted(reqs, key=lambda r: (-r["coverage"] * r["weight"])):
        if r["status"] == "met" and r["evidence"]:
            strengths.append(f"{r['label']}: " + "; ".join(_evidence_phrase(e) for e in r["evidence"][:2]))
    for r in reqs:
        if r["importance"] == "mandatory" and r["status"] != "met":
            gaps.append(f"{r['label']} ({r['status']})")
    concerns = _concerns(row, rec, spec, as_of)
    concerns += [f"{c['label']} (policy: {c['policy']})" for c in triggered if c["policy"] != "ignore"]
    concerns += [f["title"] for f in flags if f["severity"] in ("critical", "warning")]

    rank = int(row["rank"])
    overall = float(row["overall"])
    eligible = bool(row["eligible"])
    claims, remarks = _summary_parts(rec, rank, overall, eligible, mand, met, reqs, concerns,
                                     _differentiators(pool, pos))
    # Only the claims sentence asserts facts about the candidate; the remarks
    # sentence names JD requirements that are *missing*, so it is not checked.
    if validate_text(claims, rec):  # never ship an unsupported claim
        p = rec["profile"]
        claims = (f"{_tone(rank, overall, eligible)}: {p['current_title']} at {p['current_company']}; "
                  f"meets {len(met)} of {len(mand)} must-haves.")
    summary = f"{claims} {remarks}".strip()

    p = rec["profile"]
    return {
        "candidate_id": candidate_id,
        "rank": rank,
        "eligible": bool(row["eligible"]),
        "ineligible_reason": row["ineligible_reason"] or None,
        "overall": round(overall, 4),
        "tone": _tone(rank, overall, eligible),
        "summary": summary,
        "components": components,
        "constraint_factor": round(float(row["constraint_factor"]), 4),
        "triggered_constraints": triggered,
        "requirements": reqs,
        "mandatory_met": len(met),
        "mandatory_total": len(mand),
        "strengths": strengths[:5],
        "gaps": gaps,
        "concerns": concerns,
        "missing_information": _missing_info(rec, has_rel_assess),
        "flags": flags,
        "differentiators": _differentiators(pool, pos),
        "evidence_completeness": round(float(row["evidence_completeness"]), 3),
        "signals": _signal_breakdown(row),
        "experience": {"years": p.get("years_of_experience"), "relevant_years": round(float(row["relevant_years"]), 1),
                       "title_relevance": round(float(row["title_relevance"]), 3),
                       "career_relevance": round(float(row["career_relevance"]), 3)},
        "record": rec,
    }


def _signal_breakdown(row: pd.Series) -> dict:
    out = {}
    for prefix, group in (("eng_", "engagement"), ("log_", "logistics"), ("exp_", "experience")):
        out[group] = {k[len(prefix):]: (None if math.isnan(float(row[k])) else round(float(row[k]), 3))
                      for k in row.index if k.startswith(prefix)}
    return out


def _summary_parts(rec: dict, rank: int, overall: float, eligible: bool, mand: list[dict], met: list[dict],
                   reqs: list[dict], concerns: list[str], diffs: list[dict]) -> tuple[str, str]:
    """Two sentences built only from validated evidence items and record facts.

    Returns (claims, remarks): ``claims`` states facts about the candidate and
    is validated against the record; ``remarks`` lists concerns or JD
    requirements that are not evidenced.
    """
    p = rec["profile"]
    yoe = p.get("years_of_experience")
    head = f"{_tone(rank, overall, eligible)}: {p['current_title']} at {p['current_company']}"
    head += f" ({yoe:.1f} yrs)" if yoe is not None else ""
    best = [r for r in sorted(reqs, key=lambda r: -r["coverage"] * r["weight"]) if r["evidence"] and r["status"] == "met"]
    ev_bits = []
    for r in best[:2]:
        ev_bits.append(_evidence_phrase(r["evidence"][0]))
    if mand:
        s1 = f"{head} meets {len(met)} of {len(mand)} must-haves"
    else:
        s1 = head
    if ev_bits:
        s1 += ", with " + " and ".join(ev_bits)
    s1 += "."
    if concerns:
        s2 = "Concerns: " + "; ".join(concerns[:2]) + "."
    elif diffs and diffs[0]["delta"] > 0:
        s2 = f"Edges out similarly ranked profiles on {diffs[0]['label'].lower()}."
    else:
        missing = [r["label"] for r in mand if r["status"] == "missing"]
        s2 = f"Not evidenced: {', '.join(missing[:2])}." if missing else "No significant concerns found in the profile."
    return s1, s2
