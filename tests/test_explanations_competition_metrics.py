import csv
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from engine.evaluation.metrics import average_precision, dcg, evaluate_ranking, ndcg, precision_at
from engine.explanations.explain import explain_candidate
from engine.explanations.validator import validate_evidence, validate_text
from engine.ranking.competition import competition_rows, validate_submission, write_submission
from engine.ranking.scorer import score_pool

REF_VALIDATOR = Path(__file__).resolve().parents[2] / "reference material" / "validate_submission.py"


@pytest.fixture(scope="module")
def pool(pool_index, sample_spec):
    return score_pool(pool_index, sample_spec, embedder=None)


def test_explanations_are_grounded(pool_index, pool, sample_spec):
    for cid in pool.table["candidate_id"]:
        e = explain_candidate(pool_index, pool, sample_spec, cid)
        rec = e["record"]
        claims = e["summary_claims"]
        assert validate_text(claims, rec) == [], (cid, e["summary"])
        for r in e["requirements"]:
            for item in r["evidence"]:
                assert validate_evidence(item, rec)


def test_explanation_content(pool_index, pool, sample_spec):
    e = explain_candidate(pool_index, pool, sample_spec, "CAND_0000001")
    assert e["rank"] <= 2 and e["tone"] == "Top match"
    assert e["mandatory_met"] >= 3
    assert sum(c["contribution"] for c in e["components"]) == pytest.approx(
        e["overall"] / e["constraint_factor"], abs=1e-3)
    stuffer = explain_candidate(pool_index, pool, sample_spec, "CAND_0000003")
    assert any(f["code"] == "uncorroborated_skill_claims" for f in stuffer["flags"])
    held = explain_candidate(pool_index, pool, sample_spec, "CAND_0000005")
    assert held["tone"] == "Held for review"


def test_validator_catches_fabrication(pool_index):
    rec = pool_index.record_by_id("CAND_0000004")  # Java developer
    assert validate_text("Strong match with Pinecone and LoRA expertise.", rec) == ["LoRA", "Pinecone"]
    assert not validate_evidence({"kind": "skill", "skill": "Pinecone"}, rec)
    assert not validate_evidence({"kind": "skill", "skill": "Java", "proficiency": "expert"}, rec)
    assert validate_evidence({"kind": "skill", "skill": "Java", "proficiency": "advanced"}, rec)
    assert not validate_evidence({"kind": "role_text", "role_index": 0, "title": "Java Developer",
                                  "company": "Flipkart", "phrases": ["learning-to-rank"]}, rec)


def test_competition_csv_is_valid(tmp_path, pool_index, pool, sample_spec):
    rows = competition_rows(pool_index, pool, sample_spec)
    out = tmp_path / "team_test.csv"
    write_submission(rows, out)
    ids = set(pool_index.candidates["candidate_id"])
    assert validate_submission(out, ids) == []
    with open(out, encoding="utf-8") as f:
        data = list(csv.reader(f))
    assert data[0] == ["candidate_id", "rank", "score", "reasoning"] and len(data) == 101
    assert len({r[3] for r in data[1:]}) > 50  # reasoning varies
    if REF_VALIDATOR.exists():
        res = subprocess.run([sys.executable, "-I", str(REF_VALIDATOR), str(out)], capture_output=True, text=True)
        assert "Submission is valid" in res.stdout, res.stdout


def test_competition_validator_catches_errors(tmp_path):
    p = tmp_path / "bad.csv"
    rows = [["candidate_id", "rank", "score", "reasoning"]]
    rows += [[f"CAND_{i:07d}", str(i), str(1 - i / 1000), "x"] for i in range(1, 100)]
    rows += [["CAND_0000001", "100", "0.95", "x"]]  # duplicate id, increasing score
    with open(p, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    errs = " ".join(validate_submission(p, {f"CAND_{i:07d}" for i in range(1, 100)}))
    assert "duplicate candidate_id" in errs and "Score increases" in errs


def test_metrics_known_values():
    assert dcg(np.array([3, 2, 0]), 3) == pytest.approx(7 + 3 / np.log2(3))
    assert ndcg(np.array([3, 2]), np.array([3, 2, 1]), 2) == pytest.approx(1.0)
    assert ndcg(np.array([0, 3]), np.array([3, 0]), 2) < 1
    assert precision_at(np.array([3, 1, 4, 5]), 4) == 0.75
    # relevant at positions 1 and 3, 2 relevant in pool: AP = (1/1 + 2/3) / 2
    assert average_precision(np.array([3, 0, 4]), np.array([3, 4, 0]), 3) == pytest.approx((1 + 2 / 3) / 2)
    m = evaluate_ranking(["a", "b"], {"a": 5, "b": 0, "c": 4})
    assert 0 < m["composite"] < 1
