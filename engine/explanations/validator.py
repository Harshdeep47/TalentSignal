"""Evidence validation: every statement must be traceable to the record.

Two layers:

1. ``validate_evidence`` checks structured evidence items (skill, role,
   phrase, signal) against the raw candidate record. Items that fail are
   dropped before any text is generated.
2. ``validate_text`` scans generated text for any known skill or technology
   name and verifies that each one actually appears in the candidate's record
   (skills list or profile text). This catches template bugs that would
   otherwise put a skill in a candidate's mouth.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from engine.taxonomy import load_taxonomy


def _record_text(rec: dict) -> str:
    p = rec["profile"]
    parts = [p.get("headline", ""), p.get("summary", ""), p.get("current_title", "")]
    for r in rec["career_history"]:
        parts += [r.get("title", ""), r.get("description", ""), r.get("company", "")]
    return " ".join(parts).lower()


def validate_evidence(item: dict[str, Any], rec: dict) -> bool:
    kind = item.get("kind")
    if kind == "skill":
        for s in rec["skills"]:
            if s["name"] == item["skill"]:
                if item.get("proficiency") and s.get("proficiency") != item["proficiency"]:
                    return False
                if item.get("assessed") is not None:
                    scores = {k.lower(): v for k, v in rec["redrob_signals"].get("skill_assessment_scores", {}).items()}
                    got = scores.get(s["name"].lower())
                    return got is not None and abs(got - item["assessed"]) < 0.51
                return True
        return False
    if kind in ("role", "role_text"):
        i = item.get("role_index")
        roles = rec["career_history"]
        if i is None or i >= len(roles):
            return False
        r = roles[i]
        if r["title"] != item.get("title") or r["company"] != item.get("company"):
            return False
        desc = r.get("description", "").lower()
        return all(ph.lower() in desc for ph in item.get("phrases", []))
    if kind == "summary_text":
        text = (rec["profile"].get("summary", "") + " " + rec["profile"].get("headline", "")).lower()
        return all(ph.lower() in text for ph in item.get("phrases", []))
    if kind == "signal":
        val = rec["redrob_signals"].get(item["signal"])
        exp = item.get("value")
        if val is None or exp is None:
            return val is None and exp is None
        if isinstance(val, bool) or isinstance(exp, bool):
            return bool(val) == bool(exp)
        return abs(float(val) - float(exp)) < 1e-6
    return False


@lru_cache(maxsize=1)
def _known_terms() -> tuple[tuple[str, re.Pattern], ...]:
    tax = load_taxonomy()
    names = {s for c in tax.concepts.values() for s in c.skills if len(s) >= 3}
    return tuple((n, re.compile(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])")) for n in sorted(names))


def validate_text(text: str, rec: dict) -> list[str]:
    """Return known skill/tech names mentioned in ``text`` that the record does not support."""
    skills = {s["name"].lower() for s in rec["skills"]}
    body = _record_text(rec)
    problems = []
    for name, pat in _known_terms():
        if pat.search(text) and name.lower() not in skills and name.lower() not in body:
            problems.append(name)
    return problems
