"""Record normalisation and validation against the candidate schema.

Philosophy: reject only what cannot be used; repair and *report* the rest.

* ``error``   -> the record is rejected (not an object, no usable id, no
                 profile). Rejected rows are listed in the data-quality report.
* ``warning`` -> the record is kept; a value was coerced, clipped, or dropped.

Missing optional values become ``None`` -- never 0 -- so downstream scoring
can treat them as "unknown" rather than as negative evidence. Sentinel values
documented in the signals reference (``-1`` for no GitHub / no offer history)
are converted to ``None`` for the same reason.

A hand-written validator is used instead of ``jsonschema`` because it is about
an order of magnitude faster on 100K records and produces repair actions, not
just pass/fail.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

ID_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
REFERENCE_ID_PATTERN = re.compile(r"^CAND_[0-9]{7}$")
COMPANY_SIZES = {"1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001-10000", "10001+"}
PROFICIENCY = {"beginner", "intermediate", "advanced", "expert"}
WORK_MODES = {"remote", "hybrid", "onsite", "flexible"}
EDU_TIERS = {"tier_1", "tier_2", "tier_3", "tier_4", "unknown"}
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_TEXT = 6000
MAX_ROLES = 25
MAX_SKILLS = 200

# name -> (kind, min, max). kind: int | float | bool | date | str | enum
SIGNAL_SPEC: dict[str, tuple[str, float | None, float | None]] = {
    "profile_completeness_score": ("float", 0, 100),
    "signup_date": ("date", None, None),
    "last_active_date": ("date", None, None),
    "open_to_work_flag": ("bool", None, None),
    "profile_views_received_30d": ("int", 0, None),
    "applications_submitted_30d": ("int", 0, None),
    "recruiter_response_rate": ("float", 0, 1),
    "avg_response_time_hours": ("float", 0, None),
    "connection_count": ("int", 0, None),
    "endorsements_received": ("int", 0, None),
    "notice_period_days": ("int", 0, 365),
    "preferred_work_mode": ("enum", None, None),
    "willing_to_relocate": ("bool", None, None),
    "github_activity_score": ("float", 0, 100),
    "search_appearance_30d": ("int", 0, None),
    "saved_by_recruiters_30d": ("int", 0, None),
    "interview_completion_rate": ("float", 0, 1),
    "offer_acceptance_rate": ("float", 0, 1),
    "verified_email": ("bool", None, None),
    "verified_phone": ("bool", None, None),
    "linkedin_connected": ("bool", None, None),
}
# Fields where the documented sentinel -1 means "not available".
MINUS_ONE_IS_MISSING = {"github_activity_score", "offer_acceptance_rate"}
SIGNAL_NAMES = list(SIGNAL_SPEC) + ["skill_assessment_scores", "expected_salary_range_inr_lpa"]


@dataclass
class Issue:
    level: str  # "error" | "warning"
    field: str
    message: str


class Normalizer:
    """Stateful per-file normaliser (tracks duplicate ids across records)."""

    def __init__(self) -> None:
        self.seen_ids: set[str] = set()

    def normalize(self, rec: Any) -> tuple[dict[str, Any] | None, list[Issue]]:
        issues: list[Issue] = []
        if not isinstance(rec, dict):
            return None, [Issue("error", "", "Record is not an object.")]

        cid = rec.get("candidate_id")
        cid = str(cid).strip() if cid is not None else ""
        if not cid or not ID_PATTERN.match(cid):
            return None, [Issue("error", "candidate_id",
                                "Missing or invalid candidate_id (1-64 chars of letters, digits, _ . -).")]
        if cid in self.seen_ids:
            return None, [Issue("error", "candidate_id", f"Duplicate candidate_id '{cid}'; first occurrence kept.")]
        if not REFERENCE_ID_PATTERN.match(cid):
            issues.append(Issue("warning", "candidate_id", "Id does not follow the CAND_XXXXXXX convention."))

        prof_in = rec.get("profile")
        if not isinstance(prof_in, dict):
            return None, [Issue("error", "profile", "Missing profile object.")]
        self.seen_ids.add(cid)

        out: dict[str, Any] = {"candidate_id": cid}
        out["profile"] = _profile(prof_in, issues)
        out["career_history"] = _career(rec.get("career_history"), issues)
        out["education"] = _education(rec.get("education"), issues)
        out["skills"] = _skills(rec.get("skills"), issues)
        out["certifications"] = _list_of_dicts(rec.get("certifications"), ("name", "issuer", "year"))
        out["languages"] = _list_of_dicts(rec.get("languages"), ("language", "proficiency"))
        out["redrob_signals"] = _signals(rec.get("redrob_signals"), issues)

        p = out["profile"]
        if not p["current_title"] and out["career_history"]:
            p["current_title"] = out["career_history"][0]["title"]
            issues.append(Issue("warning", "profile.current_title", "Filled from the most recent role."))
        if p["years_of_experience"] is None and out["career_history"]:
            months = sum(r["duration_months"] or 0 for r in out["career_history"])
            p["years_of_experience"] = round(months / 12, 1)
            issues.append(Issue("warning", "profile.years_of_experience", "Derived from career history."))
        return out, issues


# ---- helpers -------------------------------------------------------------
def clean_text(value: Any, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    s = CONTROL_CHARS.sub(" ", str(value)).strip()
    return s[:limit]


def _num(value: Any, kind: str, field: str, issues: list[Issue], lo=None, hi=None) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        issues.append(Issue("warning", field, f"Non-numeric value '{str(value)[:30]}' ignored."))
        return None
    if v != v:  # NaN
        return None
    if lo is not None and v < lo:
        issues.append(Issue("warning", field, f"Value {v} below minimum {lo}; clipped."))
        v = lo
    if hi is not None and v > hi:
        issues.append(Issue("warning", field, f"Value {v} above maximum {hi}; clipped."))
        v = hi
    return int(round(v)) if kind == "int" else float(v)


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("true", "1", "yes", "y"):
        return True
    if s in ("false", "0", "no", "n"):
        return False
    return None


def _date(value: Any, field: str, issues: list[Issue]) -> str | None:
    if value is None or value == "":
        return None
    s = str(value).strip()[:10]
    try:
        date.fromisoformat(s)
        return s
    except ValueError:
        issues.append(Issue("warning", field, f"Unparseable date '{s}' ignored."))
        return None


def _enum(value: Any, allowed: set[str], field: str, issues: list[Issue]) -> str | None:
    if value is None or value == "":
        return None
    s = str(value).strip()
    if s in allowed:
        return s
    issues.append(Issue("warning", field, f"Unknown value '{s[:30]}' ignored."))
    return None


def _profile(p: dict, issues: list[Issue]) -> dict:
    return {
        "anonymized_name": clean_text(p.get("anonymized_name"), 120),
        "headline": clean_text(p.get("headline"), 300),
        "summary": clean_text(p.get("summary")),
        "location": clean_text(p.get("location"), 120),
        "country": clean_text(p.get("country"), 80),
        "years_of_experience": _num(p.get("years_of_experience"), "float", "profile.years_of_experience", issues, 0, 60),
        "current_title": clean_text(p.get("current_title"), 150),
        "current_company": clean_text(p.get("current_company"), 150),
        "current_company_size": _enum(p.get("current_company_size"), COMPANY_SIZES, "profile.current_company_size", issues),
        "current_industry": clean_text(p.get("current_industry"), 120),
    }


def _career(roles: Any, issues: list[Issue]) -> list[dict]:
    if not isinstance(roles, list):
        if roles is not None:
            issues.append(Issue("warning", "career_history", "Not a list; ignored."))
        return []
    out = []
    for i, r in enumerate(roles[:MAX_ROLES]):
        if not isinstance(r, dict):
            continue
        f = f"career_history[{i}]"
        role = {
            "company": clean_text(r.get("company"), 150),
            "title": clean_text(r.get("title"), 150),
            "start_date": _date(r.get("start_date"), f + ".start_date", issues),
            "end_date": _date(r.get("end_date"), f + ".end_date", issues),
            "duration_months": _num(r.get("duration_months"), "int", f + ".duration_months", issues, 0, 720),
            "is_current": bool(_bool(r.get("is_current"))),
            "industry": clean_text(r.get("industry"), 120),
            "company_size": _enum(r.get("company_size"), COMPANY_SIZES, f + ".company_size", issues),
            "description": clean_text(r.get("description")),
        }
        if role["duration_months"] is None and role["start_date"]:
            end = date.fromisoformat(role["end_date"]) if role["end_date"] else None
            if end:
                st = date.fromisoformat(role["start_date"])
                role["duration_months"] = max(0, (end.year - st.year) * 12 + end.month - st.month)
        out.append(role)
    # Current role(s) first, then past roles newest first, so that
    # "role 0 = current role" holds regardless of the input order.
    current = [r for r in out if r["is_current"]]
    past = sorted([r for r in out if not r["is_current"]], key=lambda x: x["start_date"] or "", reverse=True)
    return current + past


def _education(items: Any, issues: list[Issue]) -> list[dict]:
    if not isinstance(items, list):
        return []
    out = []
    for i, e in enumerate(items[:10]):
        if not isinstance(e, dict):
            continue
        f = f"education[{i}]"
        out.append({
            "institution": clean_text(e.get("institution"), 200),
            "degree": clean_text(e.get("degree"), 80),
            "field_of_study": clean_text(e.get("field_of_study"), 120),
            "start_year": _num(e.get("start_year"), "int", f + ".start_year", issues, 1950, 2100),
            "end_year": _num(e.get("end_year"), "int", f + ".end_year", issues, 1950, 2100),
            "grade": clean_text(e.get("grade"), 40) or None,
            "tier": _enum(e.get("tier"), EDU_TIERS, f + ".tier", issues),
        })
    return out


def _skills(items: Any, issues: list[Issue]) -> list[dict]:
    if not isinstance(items, list):
        return []
    out, seen = [], set()
    for i, s in enumerate(items[:MAX_SKILLS]):
        if isinstance(s, str):
            s = {"name": s}
        if not isinstance(s, dict):
            continue
        name = clean_text(s.get("name"), 80)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        f = f"skills[{i}]"
        out.append({
            "name": name,
            "proficiency": _enum(s.get("proficiency"), PROFICIENCY, f + ".proficiency", issues),
            "endorsements": _num(s.get("endorsements"), "int", f + ".endorsements", issues, 0, None),
            "duration_months": _num(s.get("duration_months"), "int", f + ".duration_months", issues, 0, 720),
        })
    return out


def _list_of_dicts(items: Any, keys: tuple[str, ...]) -> list[dict]:
    if not isinstance(items, list):
        return []
    return [{k: (clean_text(x.get(k), 200) if not isinstance(x.get(k), (int, float)) else x.get(k)) for k in keys}
            for x in items[:30] if isinstance(x, dict)]


def _signals(sig: Any, issues: list[Issue]) -> dict:
    sig = sig if isinstance(sig, dict) else {}
    out: dict[str, Any] = {}
    for name, (kind, lo, hi) in SIGNAL_SPEC.items():
        v = sig.get(name)
        if name in MINUS_ONE_IS_MISSING and v is not None:
            try:
                if float(v) < 0:
                    v = None
            except (TypeError, ValueError):
                pass
        field = f"redrob_signals.{name}"
        if kind in ("int", "float"):
            out[name] = _num(v, kind, field, issues, lo, hi)
        elif kind == "bool":
            out[name] = _bool(v)
        elif kind == "date":
            out[name] = _date(v, field, issues)
        else:
            out[name] = _enum(v, WORK_MODES, field, issues)
    scores = sig.get("skill_assessment_scores")
    out["skill_assessment_scores"] = {}
    if isinstance(scores, dict):
        for k, v in scores.items():
            val = _num(v, "float", f"redrob_signals.skill_assessment_scores.{k}", issues, 0, 100)
            if val is not None:
                out["skill_assessment_scores"][clean_text(k, 80)] = val
    sal = sig.get("expected_salary_range_inr_lpa")
    if isinstance(sal, dict):
        lo_v = _num(sal.get("min"), "float", "redrob_signals.expected_salary_range_inr_lpa.min", issues, 0, None)
        hi_v = _num(sal.get("max"), "float", "redrob_signals.expected_salary_range_inr_lpa.max", issues, 0, None)
        out["expected_salary_range_inr_lpa"] = {"min": lo_v, "max": hi_v}
    else:
        out["expected_salary_range_inr_lpa"] = {"min": None, "max": None}
    return out
