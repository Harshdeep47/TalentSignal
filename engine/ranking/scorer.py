"""The TalentSignal scorer.

overall = ( sum_c  w_c * component_c ) * constraint_factor

Components (each in [0, 1]; weights from JobSpec.weights, normalised):
  requirements  weighted mean of requirement coverage (see features/evidence.py)
  role_fit      0.65 * current-title relevance + 0.35 * career relevance
  semantic      best calibrated embedding similarity between the JD focus and
                the candidate's role descriptions (title-trusted) or summary
  lexical       BM25 over the whole profile, as a percentile among matches
  experience    total-years band fit, relevant years, seniority alignment
  engagement    platform behaviour (activity, responsiveness, reliability)
  logistics     location, notice period, work mode

constraint_factor is the product of the factors of JD-declared conditions
with policy "penalize" (e.g. consulting-only careers). Conditions with policy
"exclude", hard requirements, and critical integrity findings remove a
candidate from the eligible shortlist instead of changing the score, so the
score always reflects evidence and eligibility is reported separately.

Ordering: eligible first, then overall score, then mandatory coverage, then
engagement, then candidate_id ascending (fully deterministic).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from engine.features import calibration as cal
from engine.features import constraints as cons
from engine.features.evidence import (
    RequirementEvidence, RoleContext, TextMatcher, adaptive_bounds, best_per_group, requirement_evidence, skill_row_strength,
)
from engine.features.signals import (
    ENGAGEMENT_WEIGHTS, EXPERIENCE_WEIGHTS, LOGISTICS_WEIGHTS, engagement_parts, evidence_completeness,
    experience_parts, logistics_parts, weighted_available,
)
from engine.features.titles import family_lookup, relevance_lookup, seniority_lookup
from engine.jd.spec import JobSpec, Requirement
from engine.preprocessing.store import DatasetIndex
from engine.retrieval.embeddings import Embedder, get_embedder
from engine.taxonomy import Taxonomy, load_taxonomy

COMPONENTS = ("requirements", "role_fit", "semantic", "lexical", "experience", "engagement", "logistics")
UNCORROBORATED_MIN_SKILLS = 4
UNCORROBORATED_MAX_RELEVANCE = 0.3


@dataclass
class ScoringOptions:
    """Switches used by ablation experiments; defaults = full system."""

    disabled_components: frozenset[str] = frozenset()
    use_assessments: bool = True
    use_text_evidence: bool = True
    use_skill_evidence: bool = True
    use_constraints: bool = True
    use_integrity: bool = True
    use_title_trust: bool = True


@dataclass
class ScoredPool:
    table: pd.DataFrame
    requirements: list[Requirement]
    evidence: dict[str, RequirementEvidence]
    context: dict = field(default_factory=dict)

    def shortlist(self, size: int | None) -> pd.DataFrame:
        elig = self.table[self.table["eligible"]]
        return elig if size is None else elig.head(int(size))


def _aux_requirement(tax: Taxonomy, cid: str) -> Requirement:
    c = tax.concepts[cid]
    return Requirement(id=f"aux_{cid}", label=c.label, concept_id=cid, skills=list(c.skills),
                       phrases=list(c.phrases), semantic=c.semantic, importance="preferred", weight=0.0)


def _req_text(req: Requirement) -> str:
    return req.semantic or (req.label + ". " + ", ".join(req.phrases[:8]))


def _months_ago(dates: pd.Series, as_of: date) -> np.ndarray:
    d = pd.to_datetime(dates.replace("", None), errors="coerce")
    m = (pd.Timestamp(as_of) - d).dt.days.to_numpy(dtype=np.float64) / 30.44
    return np.where(np.isnan(m), 0.0, np.maximum(m, 0.0))


def _percentile_positive(x: np.ndarray) -> np.ndarray:
    """Percentile of each positive score among positive scores; 0 for no match.

    Ties receive the same (highest) percentile, so identical documents always
    get identical lexical scores regardless of their position in the file.
    """
    out = np.zeros(len(x), dtype=np.float32)
    pos = x > 0
    if pos.any():
        vals = np.round(x[pos].astype(np.float64), 6)
        out[pos] = rankdata(vals, method="max") / pos.sum()
    return out


def score_pool(ix: DatasetIndex, spec: JobSpec, options: ScoringOptions | None = None,
               embedder: Embedder | None | str = "auto") -> ScoredPool:
    opt = options or ScoringOptions()
    tax = load_taxonomy()
    cand = ix.candidates
    roles = ix.roles
    n = ix.n
    as_of = date.fromisoformat(spec.as_of_date or ix.meta["as_of_date"])
    notes: list[str] = []
    if embedder == "auto":
        embedder = get_embedder() if ix.embeddings is not None else None
    semantic_ok = embedder is not None and ix.embeddings is not None
    if not semantic_ok:
        notes.append("Semantic model unavailable: semantic evidence disabled and weights re-normalised.")

    # ---- titles and roles ---------------------------------------------------
    role_rel = relevance_lookup(roles["title"], spec, tax)
    cur_rel = relevance_lookup(cand["title"], spec, tax)
    role_months = roles["months"].fillna(12).to_numpy(dtype=np.float64)
    ended = np.where(roles["is_current"].to_numpy(), "", roles["end_date"].to_numpy())
    months_ago = _months_ago(pd.Series(ended), as_of)
    recency = np.exp(-months_ago / cal.RECENCY_MONTHS)
    rcand = roles["idx"].to_numpy()
    w = role_months * recency
    career_rel = np.bincount(rcand, weights=role_rel * w, minlength=n) / np.maximum(
        np.bincount(rcand, weights=w, minlength=n), 1e-9)
    relevant_years = np.bincount(rcand, weights=role_rel * role_months, minlength=n) / 12.0
    max_role_rel = np.maximum(best_per_group(rcand, role_rel, n)[0], cur_rel)
    credibility = cal.SKILL_CREDIBILITY_FLOOR + (1 - cal.SKILL_CREDIBILITY_FLOOR) * max_role_rel
    trust = (cal.TRUST_FLOOR + (1 - cal.TRUST_FLOOR) * role_rel) if opt.use_title_trust else np.ones_like(role_rel)
    if not opt.use_title_trust:
        credibility = np.ones(n, dtype=np.float32)
    ctx = RoleContext(
        cand=rcand, text_id=roles["text_id"].to_numpy(), trust=trust.astype(np.float32),
        recency_keep=(0.5 + 0.5 * recency).astype(np.float32),
        summary_tid=cand["summary_tid"].to_numpy(), headline_tid=cand["headline_tid"].to_numpy(),
        credibility=credibility.astype(np.float32),
    )

    # ---- requirement evidence ----------------------------------------------
    matcher = TextMatcher(ix)
    sk = ix.skills
    strength = skill_row_strength(sk["level"].to_numpy(), sk["months"].to_numpy(), sk["assessed"].to_numpy())
    reqs = [r for r in spec.requirements if r.weight > 0]
    aux_ids = ["production_deployment", "computer_vision", "speech", "nlp", "information_retrieval",
               "ranking_recsys", "embeddings_retrieval", "llm_applications", "ml_foundations", "open_source"]
    aux = [_aux_requirement(tax, c) for c in aux_ids if c in tax.concepts]
    all_reqs = reqs + aux
    vectors: dict[str, np.ndarray | None] = {r.id: None for r in all_reqs}
    focus_vec = None
    focus_bounds = (cal.SEM_LO, cal.SEM_HI)
    if semantic_ok:
        texts = [_req_text(r) for r in all_reqs] + [spec.focus_text or spec.title] + list(cal.ANCHOR_TEXTS)
        enc = embedder.encode_queries(texts)  # type: ignore[union-attr]
        vectors = {r.id: enc[i] for i, r in enumerate(all_reqs)}
        focus_vec = enc[len(all_reqs)]
        focus_bounds = adaptive_bounds(focus_vec, enc[len(all_reqs) + 1:])

    evidence: dict[str, RequirementEvidence] = {}
    for r in all_reqs:
        evidence[r.id] = requirement_evidence(
            ix, r, ctx, matcher, vectors[r.id], strength,
            use_text=opt.use_text_evidence, use_skills=opt.use_skill_evidence,
            use_assessments=opt.use_assessments)

    tbl = pd.DataFrame({"idx": np.arange(n), "candidate_id": cand["candidate_id"].to_numpy()})
    if reqs:
        wts = np.array([r.weight for r in reqs], dtype=np.float64)
        cov = np.vstack([evidence[r.id].coverage for r in reqs])
        req_score = (wts[:, None] * cov).sum(axis=0) / wts.sum()
        mand = np.array([r.importance == "mandatory" for r in reqs])
        mandatory_cov = (wts[mand, None] * cov[mand]).sum(axis=0) / wts[mand].sum() if mand.any() else req_score
        preferred_cov = (wts[~mand, None] * cov[~mand]).sum(axis=0) / wts[~mand].sum() if (~mand).any() else np.nan
    else:
        req_score = np.full(n, 0.5)
        mandatory_cov = np.full(n, np.nan)
        preferred_cov = np.full(n, np.nan)
        notes.append("No requirements defined: the requirements component is neutral (0.5).")
    for r in reqs:
        ev = evidence[r.id]
        tbl[f"req_{r.id}"] = ev.coverage

    # ---- semantic (holistic) ------------------------------------------------
    # Only role descriptions (records of work) are compared with the JD focus.
    # Summaries are excluded: measured on the reference pool, every summary
    # scores 0.70-0.81 against the focus text, so they carry no signal there.
    best_role_sem_row = np.full(n, -1)
    if semantic_ok:
        sem_text = matcher.semantic(focus_vec, focus_bounds, kinds=("description",))
        role_sem = np.zeros(len(rcand), np.float32)
        ok = ctx.text_id >= 0
        role_sem[ok] = sem_text[ctx.text_id[ok]]
        role_sem = role_sem * ctx.trust * ctx.recency_keep
        semantic, best_role_sem_row = best_per_group(rcand, role_sem, n)
    else:
        semantic = np.zeros(n, np.float32)

    # ---- lexical (BM25) -----------------------------------------------------
    terms: list[tuple[str, float]] = [(spec.title, 0.5)]
    for r in reqs:
        for t in list(r.skills) + list(r.phrases):
            terms.append((t, r.weight))
    bm25_raw = ix.bm25.score(terms)
    lexical = _percentile_positive(bm25_raw)

    # ---- experience, engagement, logistics ---------------------------------
    years = cand["years_experience"].to_numpy(dtype=np.float64)
    cand_level = seniority_lookup(cand["title"], years, tax)
    exp_parts = experience_parts(years, relevant_years, cand_level, spec)
    experience = weighted_available(exp_parts, EXPERIENCE_WEIGHTS)
    eng_parts = engagement_parts(cand, as_of)
    engagement = weighted_available(eng_parts, ENGAGEMENT_WEIGHTS)
    log_parts = logistics_parts(cand, spec, tax)
    logistics = weighted_available(log_parts, LOGISTICS_WEIGHTS)
    if all(np.isnan(v).all() for v in log_parts.values()):
        notes.append("The job states no location, notice or work-mode preference: logistics is neutral.")

    components = {
        "requirements": req_score, "role_fit": 0.65 * cur_rel + 0.35 * career_rel, "semantic": semantic,
        "lexical": lexical, "experience": experience, "engagement": engagement, "logistics": logistics,
    }
    weights = spec.weights.normalized()
    disabled = set(opt.disabled_components)
    if not semantic_ok:
        disabled.add("semantic")
    active = {k: v for k, v in weights.items() if k not in disabled}
    total_w = sum(active.values())
    if total_w <= 0:
        raise ValueError("All score components are disabled.")
    active = {k: v / total_w for k, v in active.items()}
    base = np.zeros(n, dtype=np.float64)
    for k, wk in active.items():
        base += wk * np.asarray(components[k], dtype=np.float64)

    # ---- constraints --------------------------------------------------------
    families = family_lookup(cand["title"], tax)
    role_families = family_lookup(roles["title"], tax)
    role_levels = seniority_lookup(roles["title"], np.full(len(roles), 4.0), tax)
    cv = lambda cid: evidence[f"aux_{cid}"].coverage  # noqa: E731
    detectors = {
        "consulting_only": lambda: cons.consulting_only(roles, n, tax),
        "research_only": lambda: cons.research_only(roles, matcher.lower, role_families, n,
                                                    cv("production_deployment")),
        "non_coding_lead": lambda: cons.non_coding_lead(cand, roles, n, families),
        "title_chasing": lambda: cons.title_chasing(roles, n, role_levels),
        "cv_speech_only": lambda: cons.concept_dominance(
            np.maximum(cv("computer_vision"), cv("speech")),
            [cv("nlp"), cv("information_retrieval"), cv("ranking_recsys"), cv("embeddings_retrieval")]),
        "llm_wrapper_only": lambda: cons.concept_dominance(
            cv("llm_applications"),
            [cv("ml_foundations"), cv("information_retrieval"), cv("ranking_recsys"), cv("embeddings_retrieval")]),
        "closed_source_only": lambda: (np.isnan(cand["sig_github_activity_score"].to_numpy(dtype=np.float64))
                                       & (cv("open_source") < 0.2)),
        # Triggers only for candidates outside the hiring countries who have
        # explicitly said they will NOT relocate. Candidates abroad who are
        # willing to relocate are not penalised here: whether they need a visa
        # depends on citizenship, which the platform must not infer.
        "work_authorization": lambda: ((~cand["country"].isin(spec.location.countries).to_numpy())
                                       & (cand["sig_willing_to_relocate"].astype("boolean")
                                          .fillna(True).to_numpy() == False)  # noqa: E712
                                       if spec.location.countries else np.zeros(n, bool)),
    }
    factor = np.ones(n, dtype=np.float64)
    eligible = np.ones(n, dtype=bool)
    reasons: list[list[str]] = [[] for _ in range(n)]
    for c in spec.constraints:
        det = detectors.get(c.id)
        if det is None:
            continue
        hit = np.asarray(det(), dtype=bool)
        tbl[f"c_{c.id}"] = hit
        if not opt.use_constraints or c.policy == "ignore":
            continue
        if c.policy == "penalize":
            factor = np.where(hit, factor * c.factor, factor)
        elif c.policy == "exclude":
            eligible &= ~hit
            for i in np.flatnonzero(hit):
                reasons[i].append(c.label)
    overall = np.clip(base * factor, 0, 1)

    # ---- hard requirements --------------------------------------------------
    for r in reqs:
        if r.hard:
            miss = evidence[r.id].coverage < r.min_coverage
            eligible &= ~miss
            for i in np.flatnonzero(miss):
                reasons[i].append(f"Below minimum evidence for must-have: {r.label}")
    if spec.experience.hard_min and spec.experience.min_years is not None:
        miss = np.nan_to_num(years, nan=0) < spec.experience.min_years
        eligible &= ~miss
        for i in np.flatnonzero(miss):
            reasons[i].append(f"Below the minimum of {spec.experience.min_years:g} years")

    # ---- integrity ----------------------------------------------------------
    flags = ix.integrity
    crit = np.zeros(n, dtype=bool)
    crit[flags.loc[flags["severity"] == "critical", "idx"].to_numpy()] = True
    warn_n = np.bincount(flags.loc[flags["severity"] == "warning", "idx"].to_numpy(), minlength=n)
    claimed = np.zeros(n, dtype=np.int32)
    for r in reqs:
        claimed += (evidence[r.id].skill / np.maximum(credibility, 1e-9) >= 0.5).astype(np.int32)
    uncorroborated = (claimed >= UNCORROBORATED_MIN_SKILLS) & (max_role_rel < UNCORROBORATED_MAX_RELEVANCE)
    if opt.use_integrity and spec.integrity_policy == "exclude":
        eligible &= ~crit
        for i in np.flatnonzero(crit):
            reasons[i].append("Critical profile inconsistency - needs human review")

    # ---- evidence completeness ---------------------------------------------
    has_rel_assess = np.zeros(n, dtype=bool)
    for r in reqs:
        has_rel_assess |= evidence[r.id].verified
    completeness = evidence_completeness(cand, has_rel_assess)

    tbl["overall"] = overall.astype(np.float32)
    for k, v in components.items():
        tbl[k] = np.asarray(v, dtype=np.float32)
    tbl["constraint_factor"] = factor.astype(np.float32)
    tbl["mandatory_coverage"] = np.asarray(mandatory_cov, dtype=np.float32)
    tbl["preferred_coverage"] = np.asarray(preferred_cov, dtype=np.float32)
    tbl["title_relevance"] = cur_rel
    tbl["career_relevance"] = career_rel.astype(np.float32)
    tbl["relevant_years"] = relevant_years.astype(np.float32)
    tbl["evidence_completeness"] = completeness
    tbl["critical_flag"] = crit
    tbl["warning_flags"] = warn_n.astype(np.int16) + uncorroborated.astype(np.int16)
    tbl["uncorroborated_skills"] = uncorroborated
    tbl["eligible"] = eligible
    tbl["ineligible_reason"] = ["; ".join(r) for r in reasons]
    for k, v in exp_parts.items():
        tbl[f"exp_{k}"] = np.asarray(v, dtype=np.float32)
    for k, v in eng_parts.items():
        tbl[f"eng_{k}"] = np.asarray(v, dtype=np.float32)
    for k, v in log_parts.items():
        tbl[f"log_{k}"] = np.asarray(v, dtype=np.float32)

    tbl = tbl.sort_values(
        ["eligible", "overall", "mandatory_coverage", "engagement", "candidate_id"],
        ascending=[False, False, False, False, True], kind="mergesort").reset_index(drop=True)
    tbl["rank"] = np.where(tbl["eligible"], np.arange(1, n + 1), 0).astype(np.int32)

    context = {
        "as_of_date": as_of.isoformat(),
        "semantic_available": semantic_ok,
        "embedding_model": ix.meta.get("embedding_model") if semantic_ok else None,
        "weights_used": active,
        "notes": notes,
        "n_candidates": n,
        "n_eligible": int(eligible.sum()),
        "n_critical": int(crit.sum()),
        "role_relevance": role_rel,
        "requirement_ids": [r.id for r in reqs],
        "focus_bounds": focus_bounds,
        "best_semantic_role_row": best_role_sem_row,
    }
    return ScoredPool(table=tbl, requirements=reqs, evidence=evidence, context=context)
