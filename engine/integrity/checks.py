"""Profile integrity and consistency checks.

Each check returns zero or more :class:`Flag` objects carrying the evidence
that triggered them, so a recruiter can inspect the underlying fields.

Severity semantics (deliberately conservative):
  critical -- the profile is internally impossible as written (e.g. "expert"
              in several skills used for zero months). The candidate is held
              out of the eligible shortlist for *human review* by default. It is
              never labelled fraud: the data may simply be wrong.
  warning  -- a possible inconsistency worth a look; no score effect.
  info     -- data-quality observation (e.g. inverted salary range); no effect.

Checks that depend on the job (e.g. skills unsupported by any related role)
are computed by the scorer because they need the JobSpec.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

EXPERIENCE_GAP_CRITICAL_YEARS = 3.0
EXPERIENCE_GAP_WARNING_YEARS = 1.5
DURATION_DATE_TOLERANCE_MONTHS = 3
OVERLAP_INFO_MONTHS = 6


@dataclass
class Flag:
    code: str
    severity: str  # critical | warning | info
    title: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _months_between(a: str, b: str) -> int:
    da, db = date.fromisoformat(a), date.fromisoformat(b)
    return (db.year - da.year) * 12 + (db.month - da.month)


def check_record(rec: dict[str, Any], today: date | None = None) -> list[Flag]:
    flags: list[Flag] = []
    today = today or date.today()
    p = rec["profile"]
    roles = rec["career_history"]
    skills = rec["skills"]
    sig = rec["redrob_signals"]

    # 1. Expert proficiency with zero months of use.
    expert_zero = [s["name"] for s in skills if s.get("proficiency") == "expert" and s.get("duration_months") == 0]
    if expert_zero:
        sev = "critical" if len(expert_zero) >= 2 else "warning"
        flags.append(Flag(
            "expert_zero_duration", sev, "Expert skills with zero months of use",
            f"{len(expert_zero)} skill(s) marked 'expert' with duration 0 months: {', '.join(expert_zero[:6])}.",
            {"skills": expert_zero},
        ))

    # 2. Stated experience vs. the sum of role durations.
    yoe = p.get("years_of_experience")
    months = [r["duration_months"] for r in roles if r.get("duration_months") is not None]
    if yoe is not None and months:
        computed = sum(months) / 12.0
        gap = yoe - computed
        if abs(gap) > EXPERIENCE_GAP_WARNING_YEARS:
            sev = "critical" if abs(gap) > EXPERIENCE_GAP_CRITICAL_YEARS else "warning"
            direction = "more" if gap > 0 else "less"
            flags.append(Flag(
                "experience_mismatch", sev, "Stated experience does not match career history",
                f"Profile states {yoe:.1f} years; listed roles add up to {computed:.1f} years "
                f"({abs(gap):.1f} years {direction}).",
                {"stated_years": yoe, "computed_years": round(computed, 1)},
            ))

    # 3. Assessment results for skills the candidate does not list.
    listed = {s["name"].lower() for s in skills}
    unlisted = [k for k in sig.get("skill_assessment_scores", {}) if k.lower() not in listed]
    if unlisted:
        flags.append(Flag(
            "assessment_unlisted_skill", "warning", "Assessment for a skill not on the profile",
            f"Platform assessment recorded for {', '.join(unlisted[:5])}, which the profile does not list.",
            {"skills": unlisted},
        ))

    # 4. Role duration contradicting the role's own dates.
    for i, r in enumerate(roles):
        if r.get("start_date") and r.get("end_date") and r.get("duration_months") is not None:
            by_dates = _months_between(r["start_date"], r["end_date"])
            if abs(by_dates - r["duration_months"]) > DURATION_DATE_TOLERANCE_MONTHS:
                flags.append(Flag(
                    "role_duration_mismatch", "warning", "Role duration contradicts its dates",
                    f"{r['title']} at {r['company']}: {r['duration_months']} months stated, "
                    f"{by_dates} months between start and end dates.",
                    {"role_index": i},
                ))
                break
        if r.get("end_date") and r.get("start_date") and r["end_date"] < r["start_date"]:
            flags.append(Flag("role_dates_reversed", "warning", "Role ends before it starts",
                              f"{r['title']} at {r['company']} ends before its start date.", {"role_index": i}))
            break

    # 5. Dates in the future.
    future = [r for r in roles if r.get("start_date") and date.fromisoformat(r["start_date"]) > today]
    if future:
        flags.append(Flag("future_role_start", "warning", "Role starts in the future",
                          f"{len(future)} role(s) have a start date after {today.isoformat()}.", {}))

    # 6. Overlapping past roles (could be legitimate concurrent work).
    spans = sorted((r["start_date"], r["end_date"]) for r in roles
                   if r.get("start_date") and r.get("end_date") and not r.get("is_current"))
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        if s2 < e1 and _months_between(s2, min(e1, e2)) > OVERLAP_INFO_MONTHS:
            flags.append(Flag("overlapping_roles", "info", "Overlapping roles",
                              "Two past roles overlap by more than six months.", {}))
            break

    # 7. Data-quality observations (no effect on ranking).
    sal = sig.get("expected_salary_range_inr_lpa") or {}
    if sal.get("min") is not None and sal.get("max") is not None and sal["min"] > sal["max"]:
        flags.append(Flag("salary_range_inverted", "info", "Salary range minimum exceeds maximum",
                          f"Expected salary min {sal['min']} > max {sal['max']} LPA.", {}))
    if sig.get("signup_date") and sig.get("last_active_date") and sig["last_active_date"] < sig["signup_date"]:
        flags.append(Flag("activity_before_signup", "info", "Last activity precedes sign-up",
                          f"Last active {sig['last_active_date']} is before sign-up {sig['signup_date']}.", {}))
    if roles and p.get("current_title") and roles[0]["title"] and p["current_title"] != roles[0]["title"]:
        flags.append(Flag("current_title_mismatch", "info", "Headline title differs from current role",
                          f"Profile title '{p['current_title']}' vs current role '{roles[0]['title']}'.", {}))
    return flags
