# Status: completed, pending, limitations

## Acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Independent application structure | Done | `TalentSignal/` separate from reference material; no reference code copied |
| 2 | Data ingestion | Done | 5 formats, streaming, validation, quality report; `tests/test_ingestion.py` |
| 3 | Candidate understanding | Done | normalised records, roles, skills, assessments, signals, integrity |
| 4 | Ranking engine | Done | `engine/ranking/scorer.py`; 2.85 s warm on 100K |
| 5 | Evidence-based explanations | Done | validator; 0 unsupported mentions in 200 audited |
| 6 | Configurable shortlist sizes | Done | 10/25/50/100/500/1000/custom/all eligible |
| 7 | Competition mode | Done | `scripts/competition_rank.py`; passes the bundled validator |
| 8 | Backend APIs | Done | 21 API tests (+ 11 resume-ingestion API tests) |
| 9 | Frontend | Done | builds cleanly; 8 workflow tests; visually reviewed via screenshots |
| 10 | Table and cards | Done | `docs/screenshots/04_*`, `05_*` |
| 11 | Filters and sorting | Done | server-side; score, years, must-haves, integrity, skills, branch, country, city, search |
| 12 | Comparison | Done | 2-6 candidates |
| 13 | Persistent history | Done | SQLite, per-session; re-run, delete |
| 14 | Exports | Done | CSV, XLSX, JSON, JSONL, Parquet, PDF, competition CSV |
| 15 | Integrity and fairness safeguards | Done | Handbook §8, §12 |
| 16 | Automated tests | Done | 91 Python + 11 frontend, passing |
| 17 | Evaluation and benchmarks | Done (proxy labels) | `docs/reports/EVALUATION_REPORT.md` |
| 18 | Setup instructions | Done | README; clean-venv install verified (see DEVELOPMENT_LOG Phase 8) |
| 19 | Three learning documents | Done | `docs/01_…`, `02_…`, `03_…` |
| 20 | Limitations and reproducibility | Done | this file; all numbers produced by scripts |
| 21 | Resume ingestion (PDF/DOCX/ZIP → reviewed candidate profiles → existing ranking) | Done (no OCR) | `docs/RESUME_INGESTION.md`; 25 engine + 11 API + 3 UI tests; 10,000-document benchmark |

## Known limitations
1. **No ground truth.** Relevance metrics use proxy labels; on them the reference implementation scores higher
   (0.982 vs 0.951).
2. **Plain-language profiles** rank 8-97 (all in the top 100), not all near the top.
3. **JD parsing is rule-based** and taxonomy-dependent; unusual domains need manual requirements.
4. **Hand-set parameters** (affinities, calibration windows, component weights) - documented and editable,
   not learned.
5. **Sessions are not authentication.** Do not expose publicly without an auth layer.
6. **Scale**: benchmarked at 100K candidates only. Run result tables for "all eligible" hold ~100K rows per run.
7. **Single node**: thread-pool jobs and SQLite; no horizontal scaling.
8. **PDF import of JDs** is not supported (.docx/.txt/.md only); TXT candidate files must be JSONL.
9. **The "company younger than tenure" honeypot** from the spec cannot be detected: no founding dates in data.
10. **Frontend tests** are component/workflow tests with a mocked API; full browser E2E is covered by the live
    smoke test and screenshot run rather than an automated browser suite.
11. **Resume ingestion has no OCR** (scanned PDFs fail with a clear reason) and uses heuristic parsing tuned on
    common English layouts; accuracy on real resumes has not been measured (no labelled set). Resume
    candidates have no platform signals. Full list: `docs/RESUME_INGESTION.md` § Limitations.

## Possible next steps
- Collect recruiter feedback (shortlist/reject) and train a LambdaMART model on the existing features.
- Cross-encoder re-ranking of the top few hundred, evaluated with the same harness.
- Authentication (OIDC) and per-organisation datasets.
- Optional LLM assistance for JD extraction behind the existing review step.
- Resume intake: OCR for scanned PDFs (would need its own tests), a labelled real-resume set to measure parsing
  accuracy, layout-aware PDF reading for multi-column resumes, fuzzy duplicate detection.
