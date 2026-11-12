"""Build (or rebuild) the search index for a candidate file.

Usage:
    python scripts/build_index.py --candidates PATH [--out DIR] [--no-embed]

Prints timings and peak process memory and writes them into the index's
meta.json under "benchmark".
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.ingestion.fingerprint import file_fingerprint  # noqa: E402
from engine.preprocessing.index import build_index  # noqa: E402
from scripts._mem import PeakMemory  # noqa: E402


def default_index_dir(candidates: Path) -> Path:
    fp = file_fingerprint(candidates)
    return ROOT / "artifacts" / "indexes" / fp


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidates", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--no-embed", action="store_true", help="Skip the embedding model (lexical-only index)")
    args = ap.parse_args()
    out = args.out or default_index_dir(args.candidates)

    last = [0.0]

    def progress(frac: float, msg: str) -> None:
        if frac - last[0] >= 0.05 or frac >= 1.0:
            print(f"[{frac * 100:5.1f}%] {msg}", flush=True)
            last[0] = frac

    with PeakMemory() as mem:
        t = time.perf_counter()
        meta = build_index(args.candidates, out, progress=progress, embed=not args.no_embed)
        elapsed = time.perf_counter() - t
    meta["benchmark"] = {"wall_s": round(elapsed, 2), "peak_rss_mb": mem.peak_mb}
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta, indent=1))
    print(f"Index written to {out}")


if __name__ == "__main__":
    main()
