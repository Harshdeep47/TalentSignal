"""COMPETITION MODE: the original Redrob submission format.

Kept separate from product mode on purpose: nothing here constrains the
product (which supports any shortlist size), and the product never imports
this module except for the explicit competition export.

Rules implemented (submission_spec.docx, sections 2-3):
  * header exactly ``candidate_id,rank,score,reasoning``; UTF-8; .csv
  * exactly 100 data rows, ranks 1..100 each once, unique candidate ids
  * every id exists in the candidate file (checked here; the bundled
    validator does not check this)
  * scores non-increasing with rank; equal scores ordered by candidate_id
    ascending (what the bundled validator enforces)
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from engine.explanations.explain import explain_candidate
from engine.jd.spec import JobSpec
from engine.preprocessing.store import DatasetIndex
from engine.ranking.scorer import ScoredPool

HEADER = ["candidate_id", "rank", "score", "reasoning"]
N_ROWS = 100
SCORE_DECIMALS = 6
ID_RE = re.compile(r"^CAND_[0-9]{7}$")


def competition_rows(ix: DatasetIndex, pool: ScoredPool, spec: JobSpec, n: int = N_ROWS) -> pd.DataFrame:
    top = pool.shortlist(n).copy()
    if len(top) < n:
        raise ValueError(f"Only {len(top)} eligible candidates; the competition format needs exactly {n}.")
    top["score"] = top["overall"].astype(float).round(SCORE_DECIMALS)
    # Ties after rounding are broken by candidate_id ascending, as the
    # official validator requires; otherwise the engine's own order is kept.
    top = top.sort_values(["score", "candidate_id"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    top["rank"] = range(1, n + 1)
    top["reasoning"] = [
        " ".join(explain_candidate(ix, pool, spec, cid)["summary"].split()) for cid in top["candidate_id"]
    ]
    return top[HEADER]


def write_submission(rows: pd.DataFrame, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        w.writerow(HEADER)
        for r in rows.itertuples(index=False):
            w.writerow([r.candidate_id, int(r.rank), f"{r.score:.{SCORE_DECIMALS}f}", r.reasoning])


def validate_submission(path: str | Path, valid_ids: set[str] | None = None) -> list[str]:
    """Return a list of problems (empty = valid)."""
    p = Path(path)
    errors: list[str] = []
    if p.suffix.lower() != ".csv":
        errors.append("File must have a .csv extension.")
    try:
        with open(p, encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
    except UnicodeDecodeError:
        return ["File is not UTF-8."]
    if not rows or rows[0] != HEADER:
        return errors + [f"Header must be exactly: {','.join(HEADER)}"]
    data = [r for r in rows[1:] if any(c.strip() for c in r)]
    if len(data) != N_ROWS:
        errors.append(f"Expected {N_ROWS} data rows, found {len(data)}.")
    seen_ids, seen_ranks, parsed = set(), set(), []
    for i, r in enumerate(data, start=2):
        if len(r) != 4:
            errors.append(f"Row {i}: expected 4 columns.")
            continue
        cid, rank_s, score_s, reasoning = (c.strip() for c in r)
        if not ID_RE.match(cid):
            errors.append(f"Row {i}: malformed candidate_id {cid!r}.")
        if cid in seen_ids:
            errors.append(f"Row {i}: duplicate candidate_id {cid}.")
        seen_ids.add(cid)
        if valid_ids is not None and cid not in valid_ids:
            errors.append(f"Row {i}: candidate_id {cid} is not in the candidate file.")
        try:
            rank = int(rank_s)
            assert str(rank) == rank_s and 1 <= rank <= N_ROWS
        except (ValueError, AssertionError):
            errors.append(f"Row {i}: rank must be an integer 1-{N_ROWS}.")
            continue
        if rank in seen_ranks:
            errors.append(f"Row {i}: duplicate rank {rank}.")
        seen_ranks.add(rank)
        try:
            score = float(score_s)
        except ValueError:
            errors.append(f"Row {i}: score is not a number.")
            continue
        if not reasoning:
            errors.append(f"Row {i}: empty reasoning.")
        parsed.append((rank, score, cid))
    parsed.sort()
    for (r1, s1, c1), (r2, s2, c2) in zip(parsed, parsed[1:]):
        if s1 < s2:
            errors.append(f"Score increases from rank {r1} to {r2}.")
        if s1 == s2 and c1 > c2:
            errors.append(f"Equal scores at ranks {r1}/{r2} must be ordered by candidate_id ascending.")
    reasons = [r[3].strip() for r in data if len(r) == 4]
    if reasons and len(set(reasons)) == 1:
        errors.append("All reasoning strings are identical.")
    return errors
