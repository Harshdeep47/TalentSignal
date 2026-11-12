"""Requirement evidence: how strongly does each candidate demonstrate each requirement?

For requirement r and candidate i the engine combines three independent
sources of evidence, each in [0, 1]:

skill evidence  S  strongest single matching skill (any-of semantics):
                   claim  c = proficiency * (0.35 + 0.65 * usage)
                   usage  u = 1 - exp(-months_used / 18)
                   if a platform assessment a exists:  e = 0.5 * c + 0.5 * a / 100
                   else:                                e = c
                   then S = e * credibility(i)   (see calibration.py)
                   Taking the *max* (not the sum) means listing ten synonyms
                   earns no more than listing the best one -- the fix for the
                   unbounded skill aggregation that rewarded keyword stuffing.
text evidence   T  strongest single role description (or the summary), where a
                   text's match m = 1 - (1 - 0.75 * phrase_hit) * (1 - semantic)
                   and a role's evidence is m * title_trust * recency.
signal evidence G  optional platform signal (e.g. GitHub activity / 100).

coverage(i, r) = 1 - (1 - S)(1 - T)(1 - G)          ("noisy-OR")

Noisy-OR keeps coverage in [0, 1], rewards corroboration from independent
sources, and never lets one source subtract from another. Missing evidence
contributes 0, i.e. "not demonstrated" -- it is reported as missing
information, never as a negative finding.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from engine.features import calibration as cal
from engine.jd.spec import Requirement
from engine.preprocessing.store import DatasetIndex

TEXT_KINDS_FOR_EVIDENCE = ("description", "summary", "headline")


def best_per_group(group: np.ndarray, values: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Max value per group and the row index achieving it (-1 if none)."""
    best = np.zeros(n, dtype=np.float32)
    arg = np.full(n, -1, dtype=np.int64)
    if len(values) == 0:
        return best, arg
    order = np.lexsort((-values, group))
    g = group[order]
    first = np.ones(len(g), dtype=bool)
    first[1:] = g[1:] != g[:-1]
    sel = order[first]
    best[group[sel]] = values[sel]
    arg[group[sel]] = sel
    return best, arg


def calibrate_semantic(cos: np.ndarray, lo: float = cal.SEM_LO, hi: float = cal.SEM_HI) -> np.ndarray:
    return np.clip((cos - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)


def adaptive_bounds(vector: np.ndarray, anchor_vectors: np.ndarray) -> tuple[float, float]:
    """Per-query calibration window for long, free-form query texts.

    The query's median similarity to a fixed set of unrelated anchor texts is
    taken as its "unrelated" baseline (see calibration.ANCHOR_TEXTS). The
    median is used so that one anchor happening to be related to the query
    cannot move the baseline much.
    """
    base = float(np.median(anchor_vectors @ vector))
    lo = float(np.clip(base + cal.ADAPTIVE_MARGIN, 0.5, 0.8))
    return lo, lo + cal.ADAPTIVE_WIDTH


class TextMatcher:
    """Scores unique text segments against phrases and/or a semantic prototype."""

    def __init__(self, ix: DatasetIndex):
        self.ix = ix
        texts = ix.texts
        self.kinds = texts["kind"].to_numpy()
        self.mask = np.isin(self.kinds, TEXT_KINDS_FOR_EVIDENCE)
        self.lower = np.array([t.lower() if m else "" for t, m in zip(texts["text"].tolist(), self.mask)],
                              dtype=object)
        emb = ix.embeddings
        self.emb = emb if emb is not None else None

    def phrase_hits(self, phrases: list[str]) -> np.ndarray:
        terms = sorted({p.lower().strip() for p in phrases if p and len(p.strip()) >= 2}, key=len, reverse=True)
        hits = np.zeros(len(self.lower), dtype=bool)
        if not terms:
            return hits
        pattern = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(t) for t in terms) + r")(?![a-z0-9])")
        for i in np.flatnonzero(self.mask):
            if pattern.search(self.lower[i]):
                hits[i] = True
        return hits

    def semantic(self, vector: np.ndarray | None, bounds: tuple[float, float] | None = None,
                 kinds: tuple[str, ...] | None = None) -> np.ndarray:
        if vector is None or self.emb is None:
            return np.zeros(len(self.lower), dtype=np.float32)
        cos = self.emb @ vector.astype(np.float32)
        s = calibrate_semantic(cos, *(bounds or (cal.SEM_LO, cal.SEM_HI)))
        mask = self.mask if kinds is None else np.isin(self.kinds, kinds)
        s[~mask] = 0.0
        return s

    def match(self, phrases: list[str], vector: np.ndarray | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        hits = self.phrase_hits(phrases)
        sem = self.semantic(vector)
        m = 1.0 - (1.0 - cal.PHRASE_HIT_STRENGTH * hits) * (1.0 - sem)
        return m.astype(np.float32), hits, sem


@dataclass
class RoleContext:
    """Per-role arrays shared by all requirements in one scoring run."""

    cand: np.ndarray          # candidate row of each role
    text_id: np.ndarray       # description segment id (-1 if none)
    trust: np.ndarray         # title trust in [TRUST_FLOOR, 1]
    recency_keep: np.ndarray  # fraction of evidence kept given role age
    summary_tid: np.ndarray   # per candidate
    headline_tid: np.ndarray  # per candidate
    credibility: np.ndarray   # per candidate skill-claim credibility


@dataclass
class RequirementEvidence:
    coverage: np.ndarray
    skill: np.ndarray
    text: np.ndarray
    signal: np.ndarray
    best_skill_row: np.ndarray
    best_role_row: np.ndarray
    text_from_summary: np.ndarray
    verified: np.ndarray
    n_skill_matches: np.ndarray


def _gather(values: np.ndarray, ids: np.ndarray) -> np.ndarray:
    out = np.zeros(len(ids), dtype=np.float32)
    ok = ids >= 0
    out[ok] = values[ids[ok]]
    return out


def skill_row_strength(level: np.ndarray, months: np.ndarray, assessed: np.ndarray) -> np.ndarray:
    lv = np.where(np.isnan(level), 0.5, level)
    usage = np.where(np.isnan(months), 0.6, 1.0 - np.exp(-np.nan_to_num(months) / cal.SKILL_USAGE_MONTHS))
    claim = lv * (0.35 + 0.65 * usage)
    return np.where(np.isnan(assessed), claim,
                    (1 - cal.ASSESSMENT_WEIGHT) * claim + cal.ASSESSMENT_WEIGHT * assessed / 100.0
                    ).astype(np.float32)


def requirement_evidence(ix: DatasetIndex, req: Requirement, ctx: RoleContext, matcher: TextMatcher,
                         vector: np.ndarray | None, skill_strength: np.ndarray,
                         use_text: bool = True, use_skills: bool = True,
                         use_assessments: bool = True) -> RequirementEvidence:
    n = ix.n
    sk = ix.skills
    codes, vocab = ix.skill_codes
    wanted = [vocab[s.lower()] for s in req.skills if s.lower() in vocab]
    rows = np.flatnonzero(np.isin(codes, wanted)) if (wanted and use_skills) else np.array([], int)
    strength = skill_strength[rows] if use_assessments else skill_row_strength(
        sk["level"].to_numpy()[rows], sk["months"].to_numpy()[rows], np.full(len(rows), np.nan, np.float32))
    cand_of_row = sk["idx"].to_numpy()[rows]
    best_skill, arg = best_per_group(cand_of_row, strength, n)
    best_skill_row = np.where(arg >= 0, rows[np.maximum(arg, 0)], -1) if len(rows) else np.full(n, -1)
    n_matches = np.bincount(cand_of_row, minlength=n).astype(np.int16)
    assessed = sk["assessed"].to_numpy()
    verified = np.zeros(n, dtype=bool)
    has = best_skill_row >= 0
    verified[has] = ~np.isnan(assessed[best_skill_row[has]]) & use_assessments
    skill_ev = best_skill * ctx.credibility

    if use_text:
        phrases = list(req.phrases) + list(req.skills)
        match, _, _ = matcher.match(phrases, vector)
        role_vals = _gather(match, ctx.text_id) * ctx.trust * ctx.recency_keep
        role_ev, role_arg = best_per_group(ctx.cand, role_vals, n)
        self_ev = cal.SELF_DESCRIPTION_WEIGHT * np.maximum(_gather(match, ctx.summary_tid),
                                                           _gather(match, ctx.headline_tid)) * ctx.credibility
        text_ev = np.maximum(role_ev, self_ev)
        from_summary = self_ev > role_ev
    else:
        text_ev = np.zeros(n, np.float32)
        role_arg = np.full(n, -1)
        from_summary = np.zeros(n, bool)

    signal_ev = np.zeros(n, dtype=np.float32)
    if req.signal:
        col = f"sig_{req.signal}"
        if col in ix.candidates.columns:
            signal_ev = np.nan_to_num(ix.candidates[col].to_numpy(dtype=np.float32) / 100.0, nan=0.0)
            signal_ev = np.clip(signal_ev, 0, 1) * 0.8  # activity is supporting, not conclusive, evidence

    coverage = 1.0 - (1.0 - skill_ev) * (1.0 - text_ev) * (1.0 - signal_ev)
    return RequirementEvidence(
        coverage=coverage.astype(np.float32), skill=skill_ev.astype(np.float32), text=text_ev.astype(np.float32),
        signal=signal_ev, best_skill_row=best_skill_row, best_role_row=role_arg,
        text_from_summary=from_summary, verified=verified, n_skill_matches=n_matches,
    )
