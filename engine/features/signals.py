"""Behavioural (engagement), experience and logistics sub-scores.

Every function is vectorised over the candidate table and returns named
sub-scores in [0, 1] plus an availability mask. Combined scores are weighted
means over the sub-scores that are *available* for that candidate:

    combined_i = sum_k w_k * x_ik * avail_ik / sum_k w_k * avail_ik

so a missing value is neutral (it drops out) instead of counting as zero.
When nothing is available the combined score is 0.5 (no information).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from engine.jd.spec import JobSpec
from engine.taxonomy import Taxonomy

ENGAGEMENT_WEIGHTS = {
    "activity_recency": 0.25,     # days since last login
    "response_rate": 0.25,        # fraction of recruiter messages answered
    "response_speed": 0.10,       # median hours to respond
    "open_to_work": 0.15,         # explicit availability flag
    "interview_reliability": 0.15,  # fraction of scheduled interviews attended
    "offer_follow_through": 0.05,   # historical offer acceptance (if any offers)
    "recruiter_interest": 0.05,     # saved by recruiters in the last 30 days
}
LOGISTICS_WEIGHTS = {"location": 0.5, "notice": 0.35, "work_mode": 0.15}
EXPERIENCE_WEIGHTS = {"band": 0.45, "relevant": 0.35, "seniority": 0.20}

ACTIVITY_HALF_LIFE_DAYS = 90.0
RESPONSE_SPEED_HOURS = 48.0


def weighted_available(parts: dict[str, np.ndarray], weights: dict[str, float]) -> np.ndarray:
    num = 0.0
    den = 0.0
    for k, w in weights.items():
        x = parts[k]
        avail = ~np.isnan(x)
        num = num + w * np.where(avail, x, 0.0)
        den = den + w * avail
    out = np.where(den > 0, num / np.maximum(den, 1e-9), 0.5)
    return out.astype(np.float32)


def _days_since(dates: pd.Series, as_of: date) -> np.ndarray:
    d = pd.to_datetime(dates, errors="coerce")
    delta = (pd.Timestamp(as_of) - d).dt.days.to_numpy(dtype=np.float64)
    return np.where(np.isnan(delta), np.nan, np.maximum(delta, 0))


def _f(df: pd.DataFrame, col: str) -> np.ndarray:
    return pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=np.float64)


def _b(df: pd.DataFrame, col: str) -> np.ndarray:
    s = df[col]
    return np.where(s.isna(), np.nan, s.astype("boolean").fillna(False).astype(float)).astype(np.float64)


def engagement_parts(df: pd.DataFrame, as_of: date) -> dict[str, np.ndarray]:
    days = _days_since(df["sig_last_active_date"], as_of)
    hours = _f(df, "sig_avg_response_time_hours")
    saved = _f(df, "sig_saved_by_recruiters_30d")
    open_flag = _b(df, "sig_open_to_work_flag")
    return {
        "activity_recency": np.exp(-np.log(2) * days / ACTIVITY_HALF_LIFE_DAYS),
        "response_rate": _f(df, "sig_recruiter_response_rate"),
        "response_speed": 1.0 / (1.0 + hours / RESPONSE_SPEED_HOURS),
        # Passive candidates are not unavailable, so "not open" is 0.4, not 0.
        "open_to_work": np.where(np.isnan(open_flag), np.nan, 0.4 + 0.6 * open_flag),
        "interview_reliability": _f(df, "sig_interview_completion_rate"),
        "offer_follow_through": _f(df, "sig_offer_acceptance_rate"),
        "recruiter_interest": 1.0 - np.exp(-saved / 5.0),
    }


def experience_parts(years: np.ndarray, relevant_years: np.ndarray, cand_level: np.ndarray,
                     spec: JobSpec) -> dict[str, np.ndarray]:
    e = spec.experience
    y = years.astype(np.float64)
    if e.min_years is None:
        band = np.full(len(y), np.nan)
    else:
        lo = e.min_years
        hi = e.max_years if e.max_years is not None else max(lo + 10, lo * 2)
        ilo = e.ideal_min if e.ideal_min is not None else lo
        ihi = e.ideal_max if e.ideal_max is not None else hi
        band = np.select(
            [y < lo, y < ilo, y <= ihi, y <= hi],
            [0.75 * np.exp(-(lo - y) / 2.0),
             0.75 + 0.25 * (y - lo) / max(ilo - lo, 1e-9),
             1.0,
             1.0 - 0.25 * (y - ihi) / max(hi - ihi, 1e-9)],
            default=0.75 * np.exp(-(y - hi) / 6.0),
        )
        band = np.where(np.isnan(y), np.nan, band)
    target = e.relevant_min_years or (0.6 * e.ideal_min if e.ideal_min else 3.0)
    relevant = np.clip(relevant_years / max(target, 0.5), 0, 1)
    diff = cand_level - spec.seniority_level
    seniority = np.select([diff <= -3, diff == -2, diff == -1, diff == 0, diff == 1],
                          [0.3, 0.5, 0.8, 1.0, 0.95], default=0.85)
    return {"band": band, "relevant": relevant.astype(np.float64), "seniority": seniority.astype(np.float64)}


def location_fit(df: pd.DataFrame, spec: JobSpec, tax: Taxonomy) -> np.ndarray:
    loc = spec.location
    n = len(df)
    if loc.work_mode == "remote" or not (loc.preferred or loc.acceptable or loc.countries):
        return np.full(n, np.nan)
    pref = {c for p in loc.preferred for c in tax.expand_location(p)}
    acc = {c for p in loc.acceptable for c in tax.expand_location(p)}
    city = df["city"].fillna("").str.lower().to_numpy()
    country = df["country"].fillna("").to_numpy()
    reloc = _b(df, "sig_willing_to_relocate")
    in_country = np.isin(country, loc.countries) if loc.countries else np.ones(n, bool)
    is_pref = np.isin(city, list(pref))
    is_acc = np.isin(city, list(acc))
    willing = reloc == 1.0
    domestic = np.where(willing, 0.75, 0.6) if loc.relocation_considered else np.where(willing, 0.6, 0.4)
    if loc.visa_sponsorship is False:
        abroad = np.where(willing, 0.2, 0.1)
    else:
        abroad = np.where(willing, 0.5, 0.3)
    return np.select([is_pref, is_acc, in_country], [1.0, 0.9, domestic], default=abroad).astype(np.float64)


def notice_fit(df: pd.DataFrame, spec: JobSpec) -> np.ndarray:
    ideal, acc = spec.notice.ideal_max_days, spec.notice.acceptable_max_days
    d = _f(df, "sig_notice_period_days")
    if ideal is None:
        return np.full(len(df), np.nan)
    acc = acc if acc is not None and acc > ideal else ideal * 2 or 30
    out = np.select([d <= ideal, d <= acc],
                    [1.0, 1.0 - 0.3 * (d - ideal) / max(acc - ideal, 1)],
                    default=np.maximum(0.2, 0.7 * np.exp(-(d - acc) / 60.0)))
    return np.where(np.isnan(d), np.nan, out)


def work_mode_fit(df: pd.DataFrame, spec: JobSpec) -> np.ndarray:
    mode = spec.location.work_mode
    pref = df["sig_preferred_work_mode"].astype("string").fillna("").to_numpy()
    if mode is None or mode == "remote":
        return np.full(len(df), np.nan)
    table = {
        "hybrid": {"onsite": 1.0, "hybrid": 1.0, "flexible": 1.0, "remote": 0.6},
        "onsite": {"onsite": 1.0, "flexible": 1.0, "hybrid": 0.8, "remote": 0.4},
        "flexible": {"onsite": 1.0, "hybrid": 1.0, "flexible": 1.0, "remote": 1.0},
    }[mode]
    return np.array([table.get(p, np.nan) for p in pref], dtype=np.float64)


def logistics_parts(df: pd.DataFrame, spec: JobSpec, tax: Taxonomy) -> dict[str, np.ndarray]:
    return {"location": location_fit(df, spec, tax), "notice": notice_fit(df, spec),
            "work_mode": work_mode_fit(df, spec)}


def evidence_completeness(df: pd.DataFrame, has_relevant_assessment: np.ndarray) -> np.ndarray:
    """Fraction of trust-relevant fields present (0-1). Not part of the score."""
    checks = [
        has_relevant_assessment.astype(float),
        (~np.isnan(_f(df, "sig_github_activity_score"))).astype(float),
        (~np.isnan(_f(df, "sig_offer_acceptance_rate"))).astype(float),
        np.nan_to_num(_b(df, "sig_verified_email")),
        np.nan_to_num(_b(df, "sig_verified_phone")),
        np.nan_to_num(_b(df, "sig_linkedin_connected")),
        (~np.isnan(_f(df, "sig_interview_completion_rate"))).astype(float),
        np.nan_to_num(_f(df, "sig_profile_completeness_score") / 100.0),
    ]
    return np.mean(np.vstack(checks), axis=0).astype(np.float32)
