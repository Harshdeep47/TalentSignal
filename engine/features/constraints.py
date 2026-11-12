"""Detection of JD-declared conditions (constraints).

Each detector returns a boolean array "candidate triggers this condition".
What happens next is decided by the constraint's *policy* in the JobSpec
(ignore / penalize / exclude), which the recruiter can change. Detectors only
use fields that are actually in the profile; when the needed evidence is
missing they do not trigger (absence of data is never treated as guilt).
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from engine.taxonomy import Taxonomy

SHORT_STINT_MONTHS = 18
NON_CODING_TITLE = re.compile(r"\b(?:architect|director|head of|vp|vice president|engineering manager|cto)\b", re.I)
RESEARCH_TEXT = re.compile(r"\b(?:research lab|academic|thesis|published (?:a )?paper|phd research|postdoc)\b", re.I)


def consulting_only(roles: pd.DataFrame, n: int, tax: Taxonomy) -> np.ndarray:
    company = roles["company"].str.lower().str.strip()
    industry = roles["industry"].str.lower().str.strip()
    is_c = company.isin(tax.consulting_companies) | industry.isin(tax.consulting_industries)
    total = np.bincount(roles["idx"], minlength=n)
    consult = np.bincount(roles["idx"], weights=is_c.to_numpy(float), minlength=n)
    return (total > 0) & (consult == total)


def non_coding_lead(cand: pd.DataFrame, roles: pd.DataFrame, n: int, families: np.ndarray) -> np.ndarray:
    cur = roles[roles["order"] == 0]
    months = np.zeros(n)
    months[cur["idx"].to_numpy()] = cur["months"].fillna(0).to_numpy()
    title_hit = cand["title"].fillna("").str.contains(NON_CODING_TITLE).to_numpy()
    return (title_hit | (families == "eng_management")) & (months >= 18)


def title_chasing(roles: pd.DataFrame, n: int, role_levels: np.ndarray) -> np.ndarray:
    """>= 3 of the last four roles shorter than 18 months AND >= 2 seniority steps up."""
    recent = roles[roles["order"] < 4].assign(level=role_levels[roles["order"].to_numpy() < 4])
    short = recent["months"].fillna(99) <= SHORT_STINT_MONTHS
    n_short = np.bincount(recent["idx"], weights=short.to_numpy(float), minlength=n)
    # roles are ordered newest first; count increases in level going forward in time
    r = recent.sort_values(["idx", "order"], ascending=[True, False])
    lv = r["level"].to_numpy()
    same = np.r_[False, r["idx"].to_numpy()[1:] == r["idx"].to_numpy()[:-1]]
    ups = np.r_[False, lv[1:] > lv[:-1]] & same
    n_ups = np.bincount(r["idx"], weights=ups.astype(float), minlength=n)
    return (n_short >= 3) & (n_ups >= 2)


def research_only(roles: pd.DataFrame, texts_lower: np.ndarray, families_roles: np.ndarray, n: int,
                  production_evidence: np.ndarray) -> np.ndarray:
    tid = roles["text_id"].to_numpy()
    # Regex once per *unique* text segment, then gather per role.
    per_text = np.zeros(len(texts_lower) + 1, dtype=bool)
    for t in np.unique(tid[tid >= 0]):
        per_text[t] = bool(RESEARCH_TEXT.search(texts_lower[t]))
    research_text = per_text[np.where(tid >= 0, tid, len(texts_lower))]
    research_role = research_text | (families_roles == "ai_research")
    total = np.bincount(roles["idx"], minlength=n)
    res = np.bincount(roles["idx"], weights=research_role.astype(float), minlength=n)
    return (total > 0) & (res == total) & (production_evidence < 0.3)


def concept_dominance(dominant: np.ndarray, others: list[np.ndarray], threshold: float = 0.5,
                      floor: float = 0.3) -> np.ndarray:
    """Candidate's evidence is strong for one concept group but weak for all the others."""
    best_other = np.max(np.vstack(others), axis=0) if others else np.zeros_like(dominant)
    return (dominant >= threshold) & (best_other < floor)
