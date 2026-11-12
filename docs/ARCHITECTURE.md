# TalentSignal architecture

```
                 ┌──────────────────────────── frontend/ (React + TypeScript + Vite) ─────────────────────────┐
 browser ──────► │ Dashboard · Datasets · JD workspace · Results (table/cards) · Candidate · Compare · History │
                 └──────────────┬─────────────────────────────────────────────────────────────────────────────┘
                                │ JSON over /api  (X-Session-Id header)
                 ┌──────────────▼──────────── backend/app (FastAPI) ───────────────────────────────────────────┐
                 │ api/routes.py  →  services/ datasets · runs · shortlists · exports · jobs                   │
                 │ database/db.py (SQLite, WAL)       core/ config · security · errors                         │
                 │ JobManager (thread pool, progress, cancel)      IndexCache / pool LRU (in memory)            │
                 └──────────────┬─────────────────────────────────────────────────────────────────────────────┘
                                │ plain Python calls (no web code in the engine)
                 ┌──────────────▼──────────── engine/ (library) ──────────────────────────────────────────────┐
                 │ ingestion  readers (streaming) · validation (normalise, repair, report) · fingerprint     │
                 │ preprocessing  index.build_index → artifacts/indexes/<fingerprint>/ · store.DatasetIndex   │
                 │ jd  parser (rules) → JobSpec (pydantic, editable) · documents (.docx/.txt/.md)             │
                 │ retrieval  bm25 (sparse) · embeddings (bge-small, offline)                                │
                 │ features  evidence · titles · signals · constraints · calibration                         │
                 │ ranking  scorer.score_pool → ScoredPool · competition (100-row CSV)                       │
                 │ integrity  record checks        explanations  explain · validator                         │
                 │ evaluation  metrics · proxy_labels · adversarial                                          │
                 └─────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Data flow

1. **Ingest** (background job): stream records → normalise/validate → write `records.jsonl` + byte offsets,
   columnar tables (`candidates`, `roles`, `skills`, `texts`), integrity flags, quality report.
2. **Index**: unique text segments → BM25 sparse matrix (via a candidate×segment incidence matrix) and
   embeddings (one vector per unique segment). Index directory name = full-file BLAKE2b fingerprint, so an
   identical file is never indexed twice and a modified file never reuses a stale index.
3. **Understand the job**: JD text → `JobSpec` (requirements with importance/weights/source sentences,
   experience, location, notice, constraints, component weights). Recruiter edits it in the UI.
4. **Score** (background job): `score_pool(index, spec)` computes all components for every candidate,
   vectorised (≈2.9 s for 100K warm), applies policies and eligibility, orders deterministically.
5. **Persist**: run metadata + spec in SQLite; result table (shortlist + held-for-review rows + display
   columns) in `artifacts/runs/<run_id>.parquet`.
6. **Serve**: paging/filter/sort/facets from the result table; candidate detail and compare from the scored
   pool (LRU; recomputed deterministically from the stored spec after a restart).

## Key design decisions

| Decision | Why |
|---|---|
| Engine is a plain library | Testable without HTTP; reused by CLI, competition mode, evaluation and API |
| Work on unique text segments | Reference data has 44 distinct role descriptions for 300K roles; embedding 5.8K segments instead of 100K documents makes semantic evidence affordable on CPU; costs the same on unique data |
| Bounded evidence (max + noisy-OR) | Keyword stuffing cannot raise coverage above what the single best evidence supports |
| Title-trusted text evidence | Claims in a role description count in proportion to how related that role's title is |
| Policies, not hidden multipliers | JD-declared conditions are visible, sourced, and set to ignore / penalise / exclude by the recruiter |
| Integrity → human review | Impossible profiles are held out of the shortlist with evidence, never silently deleted or called fraud |
| SQLite + Parquet | Zero-ops persistence; columnar result tables make server-side filtering of 100K rows fast |
| Threads for jobs | Heavy work is NumPy/PyTorch (releases the GIL); threads share the in-memory index cache |
| Rule-based JD parser | Works offline and deterministically; every extraction is inspectable and editable |
