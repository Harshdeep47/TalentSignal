"""Title relevance: how close is a job title to the role being hired for?

relevance(title) = max over the JD's target families f of
                   weight(f) * affinity(f, family(title))

If the JD names no recognisable family, a token-overlap fallback compares the
title with the JD title, so the engine still behaves sensibly for roles
outside the taxonomy.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from engine.jd.spec import JobSpec
from engine.taxonomy import Taxonomy

_STOP = {"senior", "junior", "lead", "staff", "principal", "the", "and", "of", "for", "team", "founding", "i", "ii"}


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in _STOP}


def title_relevance(title: str, spec: JobSpec, tax: Taxonomy) -> float:
    if spec.role_families:
        fam = tax.family_of(title)
        return max(w * tax.family_affinity(f, fam) for f, w in spec.role_families.items())
    a, b = _tokens(title), _tokens(spec.title)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def relevance_lookup(titles: pd.Series, spec: JobSpec, tax: Taxonomy) -> np.ndarray:
    """Vectorised relevance for a column of titles (computed once per distinct title)."""
    uniq = titles.fillna("").unique()
    table = {t: title_relevance(t, spec, tax) for t in uniq}
    return titles.fillna("").map(table).to_numpy(dtype=np.float32)


def family_lookup(titles: pd.Series, tax: Taxonomy) -> np.ndarray:
    uniq = titles.fillna("").unique()
    table = {t: tax.family_of(t) for t in uniq}
    return titles.fillna("").map(table).to_numpy()


def seniority_lookup(titles: pd.Series, years: np.ndarray, tax: Taxonomy) -> np.ndarray:
    """Seniority level from title keywords; untitled levels inferred from years."""
    uniq = titles.fillna("").unique()
    explicit = {}
    for t in uniq:
        words = set(re.findall(r"[a-z]+", t.lower()))
        explicit[t] = max((tax.seniority_levels[w] for w in words if w in tax.seniority_levels), default=-1)
    lv = titles.fillna("").map(explicit).to_numpy(dtype=np.float32)
    y = np.nan_to_num(years.astype(np.float32), nan=4.0)
    inferred = np.select([y < 2, y < 5, y < 10], [1, 2, 3], default=4).astype(np.float32)
    return np.where(lv >= 0, lv, inferred)
