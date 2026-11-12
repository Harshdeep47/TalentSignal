# Development log

Chronological record of decisions, measurements and corrections. Dates are 2026-11-12 (single session).

## Phase 0 - Setup and provenance
- Workspace: `d:\project 1`. Reference material in `reference material/` left untouched (verified: no writes;
  the reference `rank.py` was only executed with output redirected outside the folder).
- Reference repo has no LICENSE; all 14 commits by "Harshdeep Singh <harshdeep@example.com>". The machine's
  global git identity has the same name, which suggests common ownership but does not prove it.
  **Decision:** independent reimplementation, no code copied; documented in README.
- Node.js was not installed. Installed portable Node v24.22.3 (SHA-256 verified against nodejs.org) into
  `TalentSignal/.tools/node` instead of a system-wide install. Python venv with `--system-site-packages` for
  development (reuses the CPU torch build); a clean isolated venv is used to verify `requirements.txt`.
- Embedding model: BAAI/bge-small-en-v1.5 (MIT, 384-d). Measured ~65 long texts/s on CPU.

## Phase 1 - Data and ingestion
- Verified audit facts: 100,000 records, 465 MB, 23 signals all present, IDs unique, 48 titles, 133 skills,
  44 distinct role descriptions across 300,171 roles, 3,241 distinct summaries.
- Streaming readers (JSONL/JSON/CSV/XLSX/Parquet); tolerant normaliser (missing → None; `-1` sentinels →
  None; clipping and coercion recorded as warnings; only unusable records rejected).
- Fingerprint changed from head/tail hash to full-file BLAKE2b (test proves a middle edit is detected).
- Index build over unique segments: cold 137 s, peak 1.99 GB; embedding 108 s of that.

## Phase 2 - Ranking engine
- Requirement evidence = max over matching skills (bounded) combined by noisy-OR with title-trusted text
  evidence and optional signals. Fixes the unbounded skill sum of the reference.
- Semantic calibration measured with `scripts/calibrate_semantic.py`: unrelated descriptions 0.41-0.55,
  explicit matches 0.75-0.85 → window [0.62, 0.80] for short requirement prototypes.
- Found: the long JD "focus" text scores every summary at 0.70-0.81 (no discrimination). Decision: holistic
  semantic uses role descriptions only, with a per-query baseline from 12 unrelated anchor texts.
- Bug found: a scratch file named `profile.py` shadowed the stdlib when scripts ran from the scratchpad,
  making the embedder silently unavailable. Fixed the root cause and made `get_embedder` log load errors.
- Performance: warm scoring 9.8 s → 2.9 s (regex per unique text instead of per role; memoised query
  embeddings; integer skill codes).
- Explanations: evidence pointers stored by the scorer; validator re-checks every claim against the record.
  False positive found ("Not evidenced: Python" names a missing JD item) → only the claims sentence is
  validated; result 0 unsupported mentions in 200 audited explanations.

## Phase 3 - Evaluation
- No ground truth. Built PROXY labels from hand-graded description templates + JD-stated conditions,
  documented as proxies with a circularity caveat.
- Tests exposed: lexical percentile not tie-aware (identical profiles scored differently) - fixed; empty
  integrity table lost integer dtype - fixed; Kubernetes listed in two concepts - fixed.
- Fairness change: "work authorization" penalty originally hit all non-India candidates, including those
  willing to relocate; whether they need a visa depends on citizenship, which must not be inferred.
  Now triggers only for candidates abroad who explicitly will not relocate.
- Experiment rejected: facet-level semantic matching (each must-have as its own query). Proxy composite fell
  monotonically with its weight (0.951 → 0.883) and plain-language profiles barely moved. Removed.
- Final proxy results: TalentSignal composite 0.951 vs reference implementation 0.982 (the reference is
  better on these proxies; partly because it ranks fewer relocation-willing candidates from abroad), BM25-only
  0.825, keyword-count 0.006. Stuffers with perfect assessments: best rank 107 of 560. Impossible profiles
  eligible: 0. Look-alike groups with distinct scores: 99.4 %. Stability under ±20 % weight noise: 98.9 %
  top-100 overlap.
- BM25 component measured as having no effect on this JD's top 100 (all top candidates saturate the
  percentile). Kept at 5 % for custom requirements outside the taxonomy; documented.

## Phase 4 - Backend
- FastAPI + SQLite (WAL) + thread-pool jobs with progress, cancellation and restart recovery.
- Uploads streamed to server-chosen filenames with size limits; path imports restricted to allow-listed
  directories; CSV/XLSX formula-injection protection; security headers + CSP; uniform error JSON.
- 21 API tests (workflow, isolation between sessions, limits, every export, competition export).

## Phase 5-7 - Frontend, integration, polish
- React + TypeScript + Vite, no UI framework; design tokens in one stylesheet; IBM Plex bundled locally.
- Server-side pagination/filtering (never renders more than one page); cards lazy-load explanations.
- Visual review with headless Edge screenshots found a cramped results table and mobile overflow - fixed.
- Live smoke test on 100K: 100-row run 13 s cold; all-eligible (99,932 rows) run 5.3 s; page queries
  150-270 ms on the large run; server peak 1.66 GB.

## Phase 8 - Verification
- Clean isolated venv (no system packages) installed from `torch` CPU wheel + `requirements-dev.txt`:
  55/55 Python tests passed. Development environment: 55 Python + 8 frontend tests passed.
- Competition ranking timing: 11.9 s and 12.25 s (peak 1.41 GB) on an idle machine; 89.9 s measured once while
  a torch install and the server were running concurrently (resource contention). All under the 300 s budget.
