"""COMPETITION MODE: produce the Redrob-format top-100 CSV.

    python scripts/competition_rank.py --candidates ./candidates.jsonl --out ./submission.csv

Stages:
  1. precompute (not time-boxed by the spec): build the index for this exact
     file if no index with the same full-file fingerprint exists yet;
  2. ranking (time-boxed: <= 5 min, <= 16 GB, CPU only, no network): load the
     index, parse the JD, score all candidates, write and validate the CSV.

During stage 2 outbound network connections are blocked in-process, so any
accidental network use fails loudly instead of silently breaking the rules.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from engine.ingestion.fingerprint import file_fingerprint  # noqa: E402
from engine.jd.documents import extract_text  # noqa: E402
from engine.jd.parser import parse_job_description  # noqa: E402
from engine.preprocessing.index import build_index  # noqa: E402
from engine.preprocessing.store import DatasetIndex, IndexNotFound  # noqa: E402
from engine.ranking.competition import competition_rows, validate_submission, write_submission  # noqa: E402
from engine.ranking.scorer import score_pool  # noqa: E402
from scripts._mem import PeakMemory  # noqa: E402

# The Redrob JD belongs to the challenge organisers and is not redistributed in this repository.
# Competition mode reads it from the local challenge materials (or pass --jd).
DEFAULT_JD = ROOT.parent / "reference material" / "job_description.docx"
TIME_BUDGET_S = 300


class _NoNetwork:
    """Context manager that makes any socket connection raise."""

    def __enter__(self):
        self._orig = socket.socket.connect

        def blocked(*_a, **_k):
            raise RuntimeError("Network access attempted during the time-boxed ranking step.")

        socket.socket.connect = blocked  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc):
        socket.socket.connect = self._orig  # type: ignore[method-assign]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--jd", type=Path, default=DEFAULT_JD, help="Job description (.txt/.md/.docx)")
    ap.add_argument("--index-root", type=Path, default=ROOT / "artifacts" / "indexes")
    args = ap.parse_args()

    t0 = time.perf_counter()
    fp = file_fingerprint(args.candidates)
    index_dir = args.index_root / fp
    try:
        DatasetIndex(index_dir)
        print(f"[precompute] reusing index {index_dir.name}")
    except IndexNotFound:
        print(f"[precompute] building index for {args.candidates} (not time-boxed)")
        build_index(args.candidates, index_dir,
                    progress=lambda f, m: print(f"  [{f * 100:5.1f}%] {m}", flush=True) if int(f * 100) % 10 == 0 else None)
    t_pre = time.perf_counter() - t0

    with PeakMemory() as mem, _NoNetwork():
        t1 = time.perf_counter()
        ix = DatasetIndex(index_dir)
        if not args.jd.is_file():
            sys.exit(f"Job description not found: {args.jd}\n"
                     "Competition mode needs the Redrob challenge JD (job_description.docx from the "
                     "challenge materials), which is not included in this repository. Pass --jd PATH.")
        jd_text = extract_text(args.jd.name, args.jd.read_bytes())
        spec = parse_job_description(jd_text, known_locations=ix.candidates["location"].unique().tolist())
        pool = score_pool(ix, spec)
        rows = competition_rows(ix, pool, spec)
        write_submission(rows, args.out)
        t_rank = time.perf_counter() - t1
    problems = validate_submission(args.out, set(ix.candidates["candidate_id"]))
    report = {
        "precompute_s": round(t_pre, 2),
        "ranking_s": round(t_rank, 2),
        "ranking_peak_rss_mb": mem.peak_mb,
        "within_time_budget": t_rank <= TIME_BUDGET_S,
        "valid": not problems,
        "problems": problems[:20],
        "candidates": ix.n,
        "eligible": pool.context["n_eligible"],
        "semantic_available": pool.context["semantic_available"],
    }
    print(json.dumps(report, indent=1))
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
