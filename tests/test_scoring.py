import numpy as np
import pytest

from engine.features.evidence import best_per_group, skill_row_strength
from engine.jd.spec import ComponentWeights
from engine.preprocessing.index import build_index
from engine.preprocessing.store import DatasetIndex
from engine.ranking.scorer import ScoringOptions, score_pool
from factories import candidate, write_jsonl


def _rank(pool, cid):
    return int(pool.table.set_index("candidate_id").loc[cid, "rank"])


def _row(pool, cid):
    return pool.table.set_index("candidate_id").loc[cid]


def test_strong_engineer_beats_keyword_stuffer(pool_index, sample_spec):
    pool = score_pool(pool_index, sample_spec, embedder=None)
    assert _rank(pool, "CAND_0000001") < _rank(pool, "CAND_0000003")
    stuffer = _row(pool, "CAND_0000003")
    assert bool(stuffer["uncorroborated_skills"])
    assert stuffer["overall"] < 0.5


def test_scores_bounded_and_deterministic(pool_index, sample_spec):
    a = score_pool(pool_index, sample_spec, embedder=None).table
    b = score_pool(pool_index, sample_spec, embedder=None).table
    assert a["candidate_id"].tolist() == b["candidate_id"].tolist()
    for col in ("overall", "requirements", "role_fit", "experience", "engagement", "logistics", "lexical"):
        assert a[col].between(0, 1).all(), col


def test_critical_integrity_is_held_for_review(pool_index, sample_spec):
    pool = score_pool(pool_index, sample_spec, embedder=None)
    r = _row(pool, "CAND_0000005")
    assert not r["eligible"] and "review" in r["ineligible_reason"]
    pool2 = score_pool(pool_index, sample_spec.model_copy(update={"integrity_policy": "flag"}), embedder=None)
    assert _row(pool2, "CAND_0000005")["eligible"]


def test_constraint_policy_changes_effect(pool_index, sample_spec):
    pool = score_pool(pool_index, sample_spec, embedder=None)
    uk = _row(pool, "CAND_0000006")
    assert bool(uk["c_work_authorization"]) and uk["constraint_factor"] < 1
    spec2 = sample_spec.model_copy(deep=True)
    for c in spec2.constraints:
        if c.id == "work_authorization":
            c.policy = "exclude"
    assert not _row(score_pool(pool_index, spec2, embedder=None), "CAND_0000006")["eligible"]


def test_hard_requirement_gate(pool_index, sample_spec):
    spec = sample_spec.model_copy(deep=True)
    for r in spec.requirements:
        if r.id == "embeddings_retrieval":
            r.hard = True
    pool = score_pool(pool_index, spec, embedder=None)
    assert not _row(pool, "CAND_0000004")["eligible"]
    assert _row(pool, "CAND_0000001")["eligible"]


def test_tie_break_by_candidate_id(tmp_path, sample_spec):
    recs = [candidate(f"CAND_{i:07d}") for i in (5, 3, 9, 1)]  # identical content
    src = write_jsonl(recs, tmp_path / "t.jsonl")
    build_index(src, tmp_path / "ix", embed=False)
    t = score_pool(DatasetIndex(tmp_path / "ix"), sample_spec, embedder=None).table
    assert t["candidate_id"].tolist() == ["CAND_0000001", "CAND_0000003", "CAND_0000005", "CAND_0000009"]
    assert t["rank"].tolist() == [1, 2, 3, 4]


def test_adding_synonym_skills_does_not_inflate(tmp_path, sample_spec):
    base = candidate("CAND_0000001", skills=[("Embeddings", "advanced", 30)])
    stuffed = candidate("CAND_0000002", skills=[(s, "advanced", 30) for s in
                                                ("Embeddings", "Sentence Transformers", "Vector Search",
                                                 "Semantic Search", "Text Encoders")])
    src = write_jsonl([base, stuffed], tmp_path / "s.jsonl")
    build_index(src, tmp_path / "ix", embed=False)
    pool = score_pool(DatasetIndex(tmp_path / "ix"), sample_spec, embedder=None)
    a, b = _row(pool, "CAND_0000001"), _row(pool, "CAND_0000002")
    assert a["req_embeddings_retrieval"] == pytest.approx(b["req_embeddings_retrieval"])


def test_missing_optional_data_is_neutral(tmp_path, sample_spec):
    full = candidate("CAND_0000001")
    sparse = candidate("CAND_0000002")
    for k in ("github_activity_score", "offer_acceptance_rate", "avg_response_time_hours",
              "interview_completion_rate"):
        sparse["redrob_signals"][k] = None
    src = write_jsonl([full, sparse], tmp_path / "m.jsonl")
    build_index(src, tmp_path / "ix", embed=False)
    pool = score_pool(DatasetIndex(tmp_path / "ix"), sample_spec, embedder=None)
    a, b = _row(pool, "CAND_0000001"), _row(pool, "CAND_0000002")
    # Missing values drop out of the weighted mean instead of counting as 0.
    assert abs(float(a["engagement"]) - float(b["engagement"])) < 0.1
    assert abs(float(a["overall"]) - float(b["overall"])) < 0.05


def test_skill_strength_formula():
    s = skill_row_strength(np.array([1.0, 1.0, 0.5]), np.array([0.0, 120.0, 24.0]), np.array([np.nan, np.nan, 90.0]))
    assert s[0] == pytest.approx(0.35)          # expert used 0 months: claim heavily discounted
    assert s[1] > 0.99                           # expert with 10 years of use
    claim = 0.5 * (0.35 + 0.65 * (1 - np.exp(-24 / 18)))
    assert s[2] == pytest.approx(0.5 * claim + 0.5 * 0.9)  # assessment blended in


def test_best_per_group():
    best, arg = best_per_group(np.array([0, 0, 2, 2, 2]), np.array([0.1, 0.5, 0.3, 0.9, 0.2], np.float32), 4)
    assert best.tolist() == pytest.approx([0.5, 0, 0.9, 0])
    assert arg.tolist() == [1, -1, 3, -1]


def test_weights_normalize_and_disable(pool_index, sample_spec):
    w = ComponentWeights().normalized()
    assert sum(w.values()) == pytest.approx(1)
    pool = score_pool(pool_index, sample_spec, ScoringOptions(disabled_components=frozenset({"engagement"})),
                      embedder=None)
    assert "engagement" not in pool.context["weights_used"]
    assert "semantic" not in pool.context["weights_used"]  # no embeddings in this index
    assert sum(pool.context["weights_used"].values()) == pytest.approx(1)


def test_semantic_component_when_model_available(semantic_index, sample_spec):
    pool = score_pool(semantic_index, sample_spec)
    assert pool.context["semantic_available"]
    t = pool.table.set_index("candidate_id")
    assert t.loc["CAND_0000001", "semantic"] > t.loc["CAND_0000004", "semantic"]
