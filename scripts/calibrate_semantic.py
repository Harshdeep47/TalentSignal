"""Inspect cosine-similarity distributions used to set SEM_LO / SEM_HI.

For each taxonomy concept, prints similarity percentiles between the concept's
semantic prototype and every unique role description in an index, plus the
best and worst matching descriptions, so the calibration in
engine/features/calibration.py can be checked by eye.

Usage: python scripts/calibrate_semantic.py --index artifacts/indexes/reference_100k
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.preprocessing.store import DatasetIndex  # noqa: E402
from engine.retrieval.embeddings import get_embedder  # noqa: E402
from engine.taxonomy import load_taxonomy  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True)
    ap.add_argument("--concepts", nargs="*", default=None)
    args = ap.parse_args()
    ix = DatasetIndex(args.index)
    emb = get_embedder()
    if emb is None or ix.embeddings is None:
        sys.exit("Embedding model or index embeddings unavailable.")
    tax = load_taxonomy()
    texts = ix.texts
    desc = np.flatnonzero(texts["kind"].to_numpy() == "description")
    E = ix.embeddings[desc]
    ids = args.concepts or list(tax.concepts)
    vecs = emb.encode([tax.concepts[c].semantic for c in ids])
    allsims = []
    for cid, v in zip(ids, vecs):
        sims = E @ v
        allsims.append(sims)
        order = np.argsort(-sims)
        p = np.percentile(sims, [10, 50, 90, 99])
        print(f"\n== {cid}: p10={p[0]:.3f} p50={p[1]:.3f} p90={p[2]:.3f} p99={p[3]:.3f} max={sims.max():.3f}")
        for j in list(order[:3]) + list(order[-2:]):
            print(f"   {sims[j]:.3f}  {texts['text'].iloc[desc[j]][:110]}")
    s = np.concatenate(allsims)
    print("\nAll concept x description sims:", np.round(np.percentile(s, [25, 50, 75, 90, 95, 99]), 3))


if __name__ == "__main__":
    main()
