"""Synthetic candidate records for tests (schema-conformant, fully controlled)."""
from __future__ import annotations

import copy
from pathlib import Path

import orjson

ML_DESC = ("Owned the ranking layer for an e-commerce search product, moving from BM25 to a learning-to-rank "
           "model with embeddings and FAISS; ran offline NDCG evaluation and online A/B tests; shipped to "
           "production serving millions of users. Wrote the Python services.")
SALES_DESC = "Enterprise sales of cloud software solutions into the mid-market segment; carried a revenue quota."
BACKEND_DESC = "Java backend development at a large enterprise: Spring Boot microservices and Kafka messaging."

SIGNALS = {
    "profile_completeness_score": 80, "signup_date": "2024-01-10", "last_active_date": "2026-05-01",
    "open_to_work_flag": True, "profile_views_received_30d": 20, "applications_submitted_30d": 3,
    "recruiter_response_rate": 0.7, "avg_response_time_hours": 12, "skill_assessment_scores": {},
    "connection_count": 300, "endorsements_received": 40, "notice_period_days": 30,
    "expected_salary_range_inr_lpa": {"min": 30, "max": 45}, "preferred_work_mode": "hybrid",
    "willing_to_relocate": True, "github_activity_score": 55, "search_appearance_30d": 40,
    "saved_by_recruiters_30d": 4, "interview_completion_rate": 0.9, "offer_acceptance_rate": 0.8,
    "verified_email": True, "verified_phone": True, "linkedin_connected": True,
}


def candidate(cid: str, title: str = "Machine Learning Engineer", desc: str = ML_DESC, years: float = 7.0,
              skills: list[tuple[str, str, int]] | None = None, location: str = "Pune, Maharashtra",
              country: str = "India", company: str = "Flipkart", industry: str = "E-commerce",
              signals: dict | None = None, name: str | None = None) -> dict:
    skills = skills if skills is not None else [("Python", "advanced", 60), ("Learning to Rank", "advanced", 36),
                                                ("FAISS", "intermediate", 24), ("Embeddings", "advanced", 30)]
    months = int(years * 12)
    sig = copy.deepcopy(SIGNALS)
    sig.update(signals or {})
    return {
        "candidate_id": cid,
        "profile": {
            "anonymized_name": name or f"Person {cid[-4:]}", "headline": f"{title} | search and ranking",
            "summary": f"{title} with {years} years of experience.", "location": location, "country": country,
            "years_of_experience": years, "current_title": title, "current_company": company,
            "current_company_size": "1001-5000", "current_industry": industry,
        },
        "career_history": [{
            "company": company, "title": title, "start_date": "2019-06-01", "end_date": None,
            "duration_months": months, "is_current": True, "industry": industry, "company_size": "1001-5000",
            "description": desc,
        }],
        "education": [{"institution": "Some University", "degree": "B.Tech", "field_of_study": "Computer Science",
                       "start_year": 2012, "end_year": 2016, "grade": "8.1", "tier": "tier_2"}],
        "skills": [{"name": n, "proficiency": p, "endorsements": 5, "duration_months": m} for n, p, m in skills],
        "certifications": [], "languages": [{"language": "English", "proficiency": "professional"}],
        "redrob_signals": sig,
    }


def write_jsonl(records: list[dict], path: Path) -> Path:
    with open(path, "wb") as f:
        for r in records:
            f.write(orjson.dumps(r) + b"\n")
    return path


def standard_pool(n_filler: int = 110) -> list[dict]:
    """A pool with clear good / bad / adversarial candidates plus filler to exceed 100."""
    recs = [
        candidate("CAND_0000001"),  # strong ML search engineer
        candidate("CAND_0000002", years=6.5, signals={"recruiter_response_rate": 0.9}),
        candidate("CAND_0000003", title="HR Manager", desc=SALES_DESC, company="Infosys", industry="IT Services",
                  skills=[(s, "expert", 60) for s in ("Embeddings", "FAISS", "Pinecone", "Learning to Rank",
                                                         "Vector Search", "Python", "RAG", "Semantic Search")]),
        candidate("CAND_0000004", title="Java Developer", desc=BACKEND_DESC,
                  skills=[("Java", "advanced", 60), ("Python", "intermediate", 12)]),
        # impossible profile: expert skills used for zero months
        candidate("CAND_0000005", skills=[("Python", "expert", 0), ("FAISS", "expert", 0), ("Embeddings", "expert", 0)]),
        candidate("CAND_0000006", country="UK", location="London", signals={"willing_to_relocate": False}),
    ]
    for i in range(n_filler):
        title = ["Data Engineer", "Software Engineer", "Accountant", "Backend Engineer", "Data Scientist"][i % 5]
        desc = BACKEND_DESC if title != "Accountant" else SALES_DESC
        recs.append(candidate(f"CAND_{1000 + i:07d}", title=title, desc=desc, years=2 + (i % 12),
                              skills=[("Python", "intermediate", 6 + i % 30), ("SQL", "advanced", 24)],
                              signals={"recruiter_response_rate": round((i % 10) / 10, 2)}))
    return recs
