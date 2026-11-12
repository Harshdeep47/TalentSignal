"""PROXY relevance labels for the reference dataset.

IMPORTANT: these are heuristic labels, not recruiter judgments and not the
hidden competition ground truth (which was never available). They exist so
that changes to the ranker can be compared *consistently*, and every report
that uses them says so.

Label = hand-assigned grade of the best recent role description
        (resources/proxy_description_grades.yaml, rubric inside), then
        adjusted with the JD's explicitly stated conditions:
          - non-technical current title                      -> 0
          - critical integrity finding (impossible profile)  -> 0
          - outside India and not willing to relocate        -> -2
          - experience < 3 or > 13 years                     -> -1
          - inactive > 180 days AND response rate < 15%      -> -1
          - career entirely at IT-services / consulting firms -> -1

Circularity caveat: the scorer also reads role descriptions (through phrases
and embeddings), so agreement between the scorer and these labels is partly
built in. The labels are most useful for (a) ablations -- does removing a
component hurt? -- and (b) catching regressions, not for claiming accuracy.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from engine.features.constraints import consulting_only
from engine.preprocessing.store import DatasetIndex
from engine.taxonomy import load_taxonomy

GRADES_PATH = Path(__file__).parent / "resources" / "proxy_description_grades.yaml"
RECENT_YEARS = 6


def load_grades() -> dict[str, int]:
    return {k: int(v) for k, v in yaml.safe_load(GRADES_PATH.read_text(encoding="utf-8"))["grades"].items()}


def proxy_labels(ix: DatasetIndex) -> pd.Series:
    """Return a Series candidate_id -> proxy label (0-5)."""
    grades = load_grades()
    tax = load_taxonomy()
    texts = ix.texts["text"].tolist()
    text_grade = np.zeros(len(texts) + 1, dtype=np.int64)
    for i, t in enumerate(texts):
        for prefix, g in grades.items():
            if t.startswith(prefix):
                text_grade[i] = g
                break
    roles = ix.roles
    as_of = date.fromisoformat(ix.meta["as_of_date"])
    end = pd.to_datetime(roles["end_date"].replace("", None), errors="coerce")
    recent = roles["is_current"].to_numpy() | ((pd.Timestamp(as_of) - end).dt.days.to_numpy() < 365 * RECENT_YEARS)
    tid = roles["text_id"].to_numpy()
    g = np.where((tid >= 0) & recent, text_grade[np.where(tid >= 0, tid, len(texts))], 0)
    n = ix.n
    label = np.zeros(n, dtype=np.int64)
    np.maximum.at(label, roles["idx"].to_numpy(), g)

    cand = ix.candidates
    fam = cand["title"].map(lambda t: tax.family_of(t)).to_numpy()
    label[fam == "non_technical"] = 0

    flags = ix.integrity
    crit = flags.loc[flags["severity"] == "critical", "idx"].to_numpy()
    label[crit] = 0
    abroad = (cand["country"].to_numpy() != "India") & (cand["sig_willing_to_relocate"].fillna(False).to_numpy() != True)  # noqa: E712
    label = label - 2 * abroad
    yoe = cand["years_experience"].fillna(0).to_numpy()
    label = label - ((yoe < 3) | (yoe > 13))
    days = (pd.Timestamp(as_of) - pd.to_datetime(cand["sig_last_active_date"], errors="coerce")).dt.days.to_numpy()
    resp = cand["sig_recruiter_response_rate"].fillna(0).to_numpy()
    label = label - ((days > 180) & (resp < 0.15))
    label = label - consulting_only(roles, n, tax)
    label = np.clip(label, 0, 5)
    return pd.Series(label, index=cand["candidate_id"].to_numpy(), name="proxy_label")
