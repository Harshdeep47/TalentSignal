import io
import zipfile

import pytest

from engine.jd.documents import DocumentError, extract_text
from engine.jd.parser import parse_job_description


def test_sample_jd_structure(sample_spec):
    s = sample_spec
    mandatory = {r.id for r in s.requirements if r.importance == "mandatory"}
    assert {"embeddings_retrieval", "vector_search_infra", "python", "ranking_evaluation"} <= mandatory
    preferred = {r.id for r in s.requirements if r.importance == "preferred"}
    assert {"llm_finetuning", "learning_to_rank_models", "open_source"} <= preferred
    assert (s.experience.min_years, s.experience.max_years) == (5, 9)
    assert (s.experience.ideal_min, s.experience.ideal_max) == (6, 8)
    assert set(s.location.preferred) == {"pune", "noida"}
    assert s.location.visa_sponsorship is False
    assert s.location.work_mode == "hybrid"
    assert s.notice.ideal_max_days == 30
    ids = {c.id for c in s.constraints}
    assert {"consulting_only", "research_only", "non_coding_lead", "title_chasing", "cv_speech_only",
            "work_authorization"} <= ids
    assert all(r.source_text for r in s.requirements)  # every extraction is traceable
    assert "search_ranking" in s.role_families and "ml_engineering" in s.role_families


def test_final_note_is_ignored(sample_spec):
    # "Pinecone" / "RAG" appear in the closing "Final note" as *negative* examples; the
    # parser must not turn context sections into requirements.
    srcs = " ".join(r.source_text or "" for r in sample_spec.requirements)
    assert "Final note" not in srcs and "keyword" not in srcs.lower()


def test_generic_backend_jd():
    jd = """Backend Engineer
Requirements:
- 3+ years building REST APIs in Go or Java
- Experience with Kubernetes and Docker
Nice to have:
- Kafka or other streaming systems
Location: Bangalore, India (onsite)
"""
    s = parse_job_description(jd)
    assert s.title == "Backend Engineer"
    req = {r.id: r.importance for r in s.requirements}
    assert req.get("backend_engineering") == "mandatory"
    assert req.get("cloud_devops") == "mandatory"
    assert req.get("distributed_systems") == "preferred"
    assert s.experience.min_years == 3
    assert "bangalore" in s.location.preferred and s.location.work_mode == "onsite"
    assert "backend" in s.role_families


def test_unknown_jd_produces_notes():
    s = parse_job_description("Pastry Chef\nMust have: love of croissants")
    assert s.extraction_notes


def test_docx_extraction_and_zip_bomb_guard():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:p><w:r><w:t>Senior Engineer</w:t></w:r></w:p></w:document>")
    assert extract_text("jd.docx", buf.getvalue()) == "Senior Engineer"
    with pytest.raises(DocumentError):
        extract_text("jd.docx", b"not a zip")
    with pytest.raises(DocumentError):
        extract_text("jd.pdf", b"%PDF")
