"""Write a small synthetic candidate pool so the app can be tried without any external data.

    python scripts/make_sample_dataset.py [--out data/sample_candidates.jsonl] [--filler 110]

The records come from tests/factories.py (the same fictional pool the test suite uses):
a strong ML search engineer, a keyword stuffer, an impossible profile that is held for
review, other profiles, and generic filler candidates. Upload the file on the Datasets
page, or point TALENTSIGNAL_LIBRARY_DATASETS at it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from factories import standard_pool, write_jsonl  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "sample_candidates.jsonl")
    ap.add_argument("--filler", type=int, default=110, help="number of generic filler candidates")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    records = standard_pool(n_filler=args.filler)
    write_jsonl(records, args.out)
    print(f"Wrote {len(records)} synthetic candidates to {args.out}")


if __name__ == "__main__":
    main()
