# Limitations and Future Improvements

Everything in **Completed** exists and is tested. Everything in **Proposed** is a suggestion that does not exist in the code.

## Completed (verified in the repository)

Configurable JD parsing with source sentences; bounded evidence scoring with seven components; semantic and lexical relevance; integrity checks; editable policies and gates; grounded, validated explanations; shortlist sizes from 10 to all eligible; FastAPI backend with jobs, persistence, exports and session separation; React frontend with filters, comparison, history and shortlists; competition mode; 63 automated tests; evaluation harness; measured benchmarks at 100,000 candidates.

## Limitations, impact and proposed improvements

| Limitation (where in code) | Why it matters / user impact | Proposed improvement | Trade-off introduced |
|---|---|---|---|
| No ground-truth evaluation; proxy labels only (`engine/evaluation/proxy_labels.py`) | Quality claims are comparative; reference scores higher on proxies | Collect recruiter feedback; pairwise judgements; online A/B test | Needs real users, consent, time; position bias in feedback |
| Title relevance is a hub (`features/titles.py`, trust and credibility in `scorer.py`) | Plain-language candidates with generic titles are under-rated (Book 1, Part 7) | Description-informed relevance, e.g. raise trust when a description strongly matches | Embellished or shuffled descriptions gain trust; must be checked against stuffing tests |
| Hand-set affinity table and calibration (`taxonomy.yaml`, `calibration.py`) | Embedded judgement; may not fit other domains | Learn affinities from feedback; re-run calibration per model and domain | Needs data; risk of overfitting to one organisation |
| Rule-based JD parser and taxonomy coverage (`jd/parser.py`) | Unusual JDs or domains extract poorly; granularity quirks | Optional LLM-assisted extraction behind the existing review screen | Cost, latency, network, possible invented requirements (mitigated by review) |
| Whole-word phrase matching (`TextMatcher.phrase_hits`) | Misses plurals and word forms | Lemmatisation or stemming of both phrases and texts | Over-matching ("ranker" vs "rank"); index rebuild |
| Missing "willing to relocate" treated as not willing (`location_fit`) | Small non-neutral default | Treat missing as neutral (drop from mean) or a middle value | Slightly more lenient location scores |
| Experience-mismatch check flags long unlisted gaps (`integrity/checks.py`) | False positives held for review | Allow a declared career break; raise threshold; show as warning when roles appear incomplete | More false negatives (impossible profiles pass) |
| Lexical percentile is pool-relative (`_percentile_positive`) | Tiny pools give extreme lexical values (Ravi got 1.0 of 3) | Absolute BM25 normalisation (e.g. score / score of an ideal document) | Harder to make comparable across queries |
| No authentication (`core/security.py` session ids) | Unsafe for public hosting | OIDC, roles, audit log, TLS | Operational complexity |
| SQLite and in-process jobs | Single node; jobs die with the process | PostgreSQL, task queue, workers | More infrastructure |
| Index build holds rows in memory (`build_index`) | ~2 GB at 100,000; ~20 GB estimated at 1 M | Chunked Arrow writes, multi-process parsing | Code complexity; deterministic merging |
| Result file and DB row not written atomically (`RunService.create`) | Rare `results_missing` after a crash | Write file to temp name, rename, then commit row | Minor |
| No migration framework (`db.py`; one hand-written v1→v2 migration) | Altering tables needs manual code | Versioned migrations (e.g. Alembic or a small runner) | Another dependency |
| No demographic fairness audit | Fairness is designed, not measured | Audit selection rates where lawful data exists | Privacy and legal constraints |
| No PDF job descriptions | JDs must be pasted or uploaded as DOCX/TXT/MD | Reuse the résumé PDF extractor for JDs | Layout noise in JD text |
| Résumé ingestion has no OCR and rule-based parsing (`engine/resumes/`) | Scanned PDFs fail; unusual layouts need manual correction; accuracy on real résumés not measured | OCR with its own tests; layout-aware PDF reading; a labelled résumé set | OCR errors; more dependencies; privacy of a labelled set |
| Frontend tests mock the API | No automated full-browser E2E | Playwright E2E suite | Slower CI; browser downloads |

!!! note "How to talk about this list"
    Pick two or three items, explain the user impact, propose a fix, and name its trade-off. That is a stronger answer than listing all fifteen.
