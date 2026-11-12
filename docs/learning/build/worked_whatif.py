"""What-if variants of the worked example (real engine), written to worked_whatif.json."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).parent))

from engine.jd.parser import parse_job_description  # noqa: E402
from engine.preprocessing.index import build_index  # noqa: E402
from engine.preprocessing.store import DatasetIndex  # noqa: E402
from engine.ranking.scorer import ScoringOptions, score_pool  # noqa: E402
from factories import write_jsonl  # noqa: E402
from worked_example import CANDIDATES, JD  # noqa: E402


def summarize(pool):
    t = pool.table
    return [{"id": r.candidate_id, "rank": int(r.rank), "overall": round(float(r.overall), 4),
             "eligible": bool(r.eligible), "reason": r.ineligible_reason} for r in t.itertuples()]


def main() -> None:
    out = {}
    with tempfile.TemporaryDirectory() as td:
        src = write_jsonl(CANDIDATES, Path(td) / "c.jsonl")
        build_index(src, Path(td) / "ix", embed=True)
        ix = DatasetIndex(Path(td) / "ix")
        base = parse_job_description(JD)
        out["default"] = summarize(score_pool(ix, base))
        s = base.model_copy(deep=True)
        for r in s.requirements:
            if r.id == "ranking_recsys":
                r.hard = True
        out["ranking_hard"] = summarize(score_pool(ix, s))
        s = base.model_copy(deep=True)
        s.weights.role_fit = 0.35
        out["role_fit_0.35"] = summarize(score_pool(ix, s))
        out["no_lexical"] = summarize(score_pool(ix, base, ScoringOptions(disabled_components=frozenset({"lexical"}))))
        out["no_engagement"] = summarize(score_pool(ix, base, ScoringOptions(disabled_components=frozenset({"engagement"}))))
    (Path(__file__).parent / "worked_whatif.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
