"""The JobSpec: a structured, editable representation of a job description.

The JD parser produces a JobSpec, the recruiter reviews and edits it in the UI,
and the scorer consumes it. Nothing in the scorer reads raw JD text except
``focus_text`` (for semantic and lexical relevance), so every ranking decision
can be traced back to a field the recruiter could see and change.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Importance = Literal["mandatory", "preferred"]
Policy = Literal["ignore", "penalize", "exclude"]


class Requirement(BaseModel):
    """One capability the job asks for.

    Evidence for a requirement comes from any of ``skills`` (any-of semantics),
    any of ``phrases`` in career text, and semantic similarity to ``semantic``.
    """

    id: str
    label: str
    concept_id: str | None = None
    skills: list[str] = Field(default_factory=list)
    phrases: list[str] = Field(default_factory=list)
    semantic: str | None = None
    signal: str | None = None
    importance: Importance = "preferred"
    weight: float = Field(1.0, ge=0.0, le=1.0)
    # A hard requirement removes candidates whose coverage is below
    # ``min_coverage`` from the eligible shortlist (they remain inspectable).
    hard: bool = False
    min_coverage: float = Field(0.35, ge=0.0, le=1.0)
    source_text: str | None = None


class ExperienceSpec(BaseModel):
    min_years: float | None = None
    max_years: float | None = None
    ideal_min: float | None = None
    ideal_max: float | None = None
    relevant_min_years: float | None = None
    hard_min: bool = False
    source_text: str | None = None


class LocationSpec(BaseModel):
    preferred: list[str] = Field(default_factory=list)
    acceptable: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    work_mode: Literal["onsite", "hybrid", "remote", "flexible"] | None = None
    relocation_considered: bool = True
    visa_sponsorship: bool | None = None
    source_text: str | None = None


class NoticeSpec(BaseModel):
    ideal_max_days: int | None = None
    acceptable_max_days: int | None = None
    source_text: str | None = None


class ConstraintSpec(BaseModel):
    """A JD-declared condition (e.g. "consulting-only careers are not a fit").

    ``policy`` decides what happens to a candidate who triggers it:
      ignore   -- shown as a concern only
      penalize -- the overall score is multiplied by ``factor``
      exclude  -- removed from the eligible shortlist (still inspectable)
    """

    id: str
    label: str
    policy: Policy = "penalize"
    factor: float = Field(0.6, ge=0.0, le=1.0)
    source_text: str | None = None


class ComponentWeights(BaseModel):
    """Relative influence of each score component. Normalised to sum to 1."""

    requirements: float = Field(0.34, ge=0)
    role_fit: float = Field(0.20, ge=0)
    semantic: float = Field(0.12, ge=0)
    lexical: float = Field(0.05, ge=0)
    experience: float = Field(0.10, ge=0)
    engagement: float = Field(0.11, ge=0)
    logistics: float = Field(0.08, ge=0)

    def normalized(self) -> dict[str, float]:
        raw = self.model_dump()
        total = sum(raw.values())
        if total <= 0:
            raise ValueError("At least one component weight must be positive.")
        return {k: v / total for k, v in raw.items()}


class JobSpec(BaseModel):
    title: str = "Untitled role"
    seniority_level: int = 2
    role_families: dict[str, float] = Field(default_factory=dict)
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    experience: ExperienceSpec = Field(default_factory=ExperienceSpec)
    location: LocationSpec = Field(default_factory=LocationSpec)
    notice: NoticeSpec = Field(default_factory=NoticeSpec)
    constraints: list[ConstraintSpec] = Field(default_factory=list)
    weights: ComponentWeights = Field(default_factory=ComponentWeights)
    # How critical integrity findings are treated (see engine.integrity).
    integrity_policy: Literal["exclude", "flag"] = "exclude"
    # Reference date for "days since active"; None = latest activity date in
    # the dataset, so results do not drift with the wall clock.
    as_of_date: str | None = None
    focus_text: str = ""
    raw_text: str = ""
    extraction_notes: list[str] = Field(default_factory=list)

    @field_validator("requirements")
    @classmethod
    def _unique_ids(cls, reqs: list[Requirement]) -> list[Requirement]:
        ids = [r.id for r in reqs]
        if len(ids) != len(set(ids)):
            raise ValueError("Requirement ids must be unique.")
        return reqs

    def constraint(self, cid: str) -> ConstraintSpec | None:
        return next((c for c in self.constraints if c.id == cid), None)
