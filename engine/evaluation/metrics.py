"""Ranking metrics used by the original competition, implemented explicitly.

Graded relevance labels ``rel`` are integers 0-5 (5 = best).

DCG@k   = sum_{i=1..k} (2^rel_i - 1) / log2(i + 1)          (exponential gain)
NDCG@k  = DCG@k / IDCG@k, where IDCG uses the best possible ordering of the
          *whole labelled pool* (not just the returned list), so a ranking that
          misses strong candidates is penalised.
P@k     = fraction of the first k results with rel >= threshold
AP@k    = (1 / min(R, k)) * sum_{i<=k, rel_i>=threshold} P@i,
          R = number of relevant items in the pool
Composite (competition) = 0.50 NDCG@10 + 0.30 NDCG@50 + 0.15 MAP + 0.05 P@10

The competition spec does not define the gain function or the MAP cut-off;
the choices above (exponential gain, AP over the submitted top 100, relevant =
tier >= 3 as stated for P@10) are documented assumptions.
"""
from __future__ import annotations

import numpy as np

RELEVANT_THRESHOLD = 3


def dcg(rels: np.ndarray, k: int) -> float:
    r = np.asarray(rels[:k], dtype=np.float64)
    if r.size == 0:
        return 0.0
    discounts = np.log2(np.arange(2, r.size + 2))
    return float(np.sum((2.0 ** r - 1.0) / discounts))


def ndcg(ranked_rels: np.ndarray, pool_rels: np.ndarray, k: int) -> float:
    ideal = np.sort(np.asarray(pool_rels))[::-1]
    idcg = dcg(ideal, k)
    return dcg(np.asarray(ranked_rels), k) / idcg if idcg > 0 else 0.0


def precision_at(ranked_rels: np.ndarray, k: int, threshold: int = RELEVANT_THRESHOLD) -> float:
    r = np.asarray(ranked_rels[:k])
    return float(np.mean(r >= threshold)) if r.size else 0.0


def average_precision(ranked_rels: np.ndarray, pool_rels: np.ndarray, k: int = 100,
                      threshold: int = RELEVANT_THRESHOLD) -> float:
    r = np.asarray(ranked_rels[:k]) >= threshold
    total_relevant = int(np.sum(np.asarray(pool_rels) >= threshold))
    if total_relevant == 0:
        return 0.0
    hits = np.cumsum(r)
    precisions = hits / np.arange(1, r.size + 1)
    return float(np.sum(precisions * r) / min(total_relevant, k))


def evaluate_ranking(ranked_ids: list[str], labels: dict[str, int]) -> dict[str, float]:
    """All competition metrics for one ranked list against graded labels."""
    ranked = np.array([labels.get(c, 0) for c in ranked_ids])
    pool = np.fromiter(labels.values(), dtype=np.int64)
    out = {
        "ndcg@10": ndcg(ranked, pool, 10),
        "ndcg@50": ndcg(ranked, pool, 50),
        "map@100": average_precision(ranked, pool, 100),
        "p@10": precision_at(ranked, 10),
        "p@5": precision_at(ranked, 5),
    }
    out["composite"] = 0.50 * out["ndcg@10"] + 0.30 * out["ndcg@50"] + 0.15 * out["map@100"] + 0.05 * out["p@10"]
    return {k: round(v, 4) for k, v in out.items()}


def overlap(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    return len(set(a) & set(b)) / max(len(a), len(b))


def kendall_tau_topk(a: list[str], b: list[str]) -> float:
    """Kendall tau over items present in both lists (rank agreement)."""
    common = [x for x in a if x in set(b)]
    if len(common) < 2:
        return 0.0
    pos_b = {x: i for i, x in enumerate(b)}
    seq = [pos_b[x] for x in common]
    n = len(seq)
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            if seq[i] < seq[j]:
                concordant += 1
            else:
                discordant += 1
    return (concordant - discordant) / (n * (n - 1) / 2)
