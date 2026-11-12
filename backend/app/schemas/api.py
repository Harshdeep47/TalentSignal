"""Request bodies validated by Pydantic. Responses are plain dicts built by services."""
from __future__ import annotations

from pydantic import BaseModel, Field

from engine.jd.spec import JobSpec


class ParseJDRequest(BaseModel):
    text: str = Field(min_length=20, max_length=60_000)
    dataset_id: str | None = None


class ImportPathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


class CreateRunRequest(BaseModel):
    dataset_id: str
    spec: JobSpec
    # None = all eligible candidates (product mode never hard-codes 100).
    shortlist_size: int | None = Field(default=100, ge=1, le=1_000_000)
    name: str | None = Field(default=None, max_length=160)


class CompareRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=2, max_length=6)


class ShortlistCreate(BaseModel):
    run_id: str
    name: str = Field(min_length=1, max_length=120)
    candidate_ids: list[str] = Field(default_factory=list, max_length=5000)


class ShortlistItem(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", max_length=2000)


class ExportRequest(BaseModel):
    format: str
    scope: str = "shortlist"
    candidate_ids: list[str] | None = Field(default=None, max_length=100_000)
    include_explanations: bool = False


# ---- resume ingestion ---------------------------------------------------------
class ResumeBatchCreate(BaseModel):
    name: str = Field(default="Resumes", max_length=120)


class ResumeRecordUpdate(BaseModel):
    """A recruiter-corrected candidate record (same schema as dataset rows).
    It is validated again by the ingestion Normalizer before it is stored."""
    record: dict


class ResumePublishRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)


class ResumeProcessRequest(BaseModel):
    retry_failed: bool = False
