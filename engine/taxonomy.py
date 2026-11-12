"""Loads the knowledge base in ``resources/taxonomy.yaml``.

The taxonomy maps raw vocabulary (skill names, phrases, job titles) onto
*concepts* and *role families*. Keeping it as data means that supporting a new
domain is an edit to a YAML file, not a code change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

RESOURCE_PATH = Path(__file__).parent / "resources" / "taxonomy.yaml"


@dataclass(frozen=True)
class Concept:
    id: str
    label: str
    category: str
    skills: tuple[str, ...]
    phrases: tuple[str, ...]
    semantic: str
    signal: str | None = None


@dataclass(frozen=True)
class RoleFamily:
    id: str
    label: str
    patterns: tuple[re.Pattern, ...]


@dataclass
class Taxonomy:
    concepts: dict[str, Concept]
    families: list[RoleFamily]
    affinity: dict[tuple[str, str], float]
    consulting_companies: frozenset[str]
    consulting_industries: frozenset[str]
    location_groups: dict[str, tuple[str, ...]]
    seniority_levels: dict[str, int]
    _family_cache: dict[str, str] = field(default_factory=dict)

    # ---- role families -------------------------------------------------
    def family_of(self, title: str) -> str:
        """Return the role-family id of a job title (first matching pattern)."""
        key = (title or "").strip().lower()
        cached = self._family_cache.get(key)
        if cached is not None:
            return cached
        family = "non_technical"
        for fam in self.families:
            if any(p.search(key) for p in fam.patterns):
                family = fam.id
                break
        self._family_cache[key] = family
        return family

    def family_affinity(self, a: str, b: str) -> float:
        if a == b:
            return 1.0
        return self.affinity.get((a, b), 0.0)

    def family_label(self, family_id: str) -> str:
        for fam in self.families:
            if fam.id == family_id:
                return fam.label
        return family_id

    # ---- seniority -----------------------------------------------------
    def seniority_of(self, title: str) -> int:
        """Seniority level implied by a title; 2 (mid-level) if no keyword."""
        words = re.findall(r"[a-z]+", (title or "").lower())
        levels = [self.seniority_levels[w] for w in words if w in self.seniority_levels]
        return max(levels) if levels else 2

    # ---- skills --------------------------------------------------------
    def concepts_for_skill(self, skill: str) -> list[str]:
        return [c.id for c in self.concepts.values() if skill in c.skills]

    def expand_location(self, place: str) -> tuple[str, ...]:
        p = place.strip().lower()
        return self.location_groups.get(p, (p,))


def _compile(patterns: list[str]) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p) for p in patterns)


@lru_cache(maxsize=4)
def load_taxonomy(path: str | None = None) -> Taxonomy:
    raw = yaml.safe_load(Path(path or RESOURCE_PATH).read_text(encoding="utf-8"))
    concepts = {
        cid: Concept(
            id=cid,
            label=c["label"],
            category=c.get("category", "other"),
            skills=tuple(c.get("skills", [])),
            phrases=tuple(p.lower() for p in c.get("phrases", [])),
            semantic=c.get("semantic", c["label"]),
            signal=c.get("signal"),
        )
        for cid, c in raw["concepts"].items()
    }
    families = [
        RoleFamily(id=f["id"], label=f["label"], patterns=_compile(f["title_patterns"]))
        for f in raw["role_families"]
    ]
    affinity: dict[tuple[str, str], float] = {}
    for a, row in raw.get("family_affinity", {}).items():
        for b, v in row.items():
            affinity[(a, b)] = float(v)
            affinity[(b, a)] = float(v)
    return Taxonomy(
        concepts=concepts,
        families=families,
        affinity=affinity,
        consulting_companies=frozenset(x.lower() for x in raw.get("consulting_companies", [])),
        consulting_industries=frozenset(x.lower() for x in raw.get("consulting_industries", [])),
        location_groups={k.lower(): tuple(v) for k, v in raw.get("location_groups", {}).items()},
        seniority_levels={k.lower(): int(v) for k, v in raw.get("seniority_levels", {}).items()},
    )
