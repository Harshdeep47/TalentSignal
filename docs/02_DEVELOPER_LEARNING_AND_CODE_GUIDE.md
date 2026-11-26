# TalentSignal - Developer Learning and Code Guide

How the codebase works, how to run it, and how to change it safely. Read the Technical Handbook first for
the *why*; this guide is the *where* and *how*.

---

## 1. Folder structure

```
TalentSignal/
├── engine/                      # the ranking engine - pure Python library, no web code
│   ├── taxonomy.py              # loads resources/taxonomy.yaml (concepts, role families, affinities)
│   ├── resources/
│   │   ├── taxonomy.yaml        # knowledge base: skills/phrases per concept, title patterns, affinities
│   │   └── jobs/*.txt           # bundled JD presets (Redrob Senior AI Engineer)
│   ├── ingestion/               # readers.py (streaming formats), validation.py (normalise), fingerprint.py
│   ├── preprocessing/           # index.py (build_index), store.py (DatasetIndex reader)
│   ├── jd/                      # spec.py (JobSpec model), parser.py (rules), documents.py (.docx/.txt/.md)
│   ├── retrieval/               # bm25.py, embeddings.py
│   ├── features/                # evidence.py, titles.py, signals.py, constraints.py, calibration.py
│   ├── ranking/                 # scorer.py (score_pool), competition.py (100-row CSV + validator)
│   ├── integrity/checks.py      # record-level consistency checks
│   ├── explanations/            # explain.py (grounded explanations), validator.py
│   └── evaluation/              # metrics.py, proxy_labels.py, adversarial.py, resources/ (proxy grades)
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI factory, middleware, SPA serving
│   │   ├── api/routes.py        # all HTTP endpoints
│   │   ├── core/                # config.py (env settings), security.py, errors.py
│   │   ├── database/db.py       # SQLite schema + tiny query helper
│   │   ├── schemas/api.py       # request bodies (Pydantic)
│   │   └── services/            # datasets.py, runs.py, shortlists.py, exports.py, jobs.py
│   └── tests/test_api.py        # end-to-end API tests
├── frontend/
│   ├── src/
│   │   ├── main.tsx, App.tsx    # entry, routes
│   │   ├── layouts/Shell.tsx    # navigation rail
│   │   ├── pages/               # Dashboard, Datasets, DatasetDetail, NewRanking, Run, Candidate, Compare, History, Shortlists
│   │   ├── components/          # ui.tsx (primitives), SpecEditor.tsx, Results.tsx
│   │   ├── services/api.ts      # API client (session header, errors, upload progress, downloads)
│   │   ├── hooks/useAsync.ts    # data loading, polling, debounce
│   │   ├── types/api.ts         # TypeScript mirror of the API JSON
│   │   ├── styles/app.css       # design system
│   │   └── test/                # vitest workflow tests + fixtures
│   └── vite.config.ts, tsconfig.json, package.json
├── scripts/                     # build_index, competition_rank, run_evaluation, smoke_test, screenshots, calibrate_semantic, download_model
├── tests/                       # engine tests (pytest) + factories.py (synthetic records)
├── docs/                        # learning documents, ARCHITECTURE.md, STATUS.md, reports/, screenshots/
├── artifacts/ (git-ignored)     # models/, indexes/<fingerprint>/, runs/<run_id>.parquet
├── data/ (git-ignored)          # talentsignal.sqlite3, uploads/
├── .tools/ (git-ignored)        # portable Node.js
├── requirements.txt, requirements-dev.txt, pyproject.toml (pytest config)
└── README.md, DEVELOPMENT_LOG.md
```

## 2. Environment setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python scripts/download_model.py
cd frontend && npm install
```
*CPU-only torch first*: otherwise pip may resolve a CUDA build of several GB.
*No global Node?* Download the Windows zip from nodejs.org, verify its SHA-256 against `SHASUMS256.txt`,
unzip to `.tools/node`, and prefix commands with `PATH="$(pwd)/.tools/node:$PATH"` (Git Bash).

## 3. Dependencies and why each exists

| Package | Used for |
|---|---|
| numpy, scipy | vectorised scoring, sparse BM25 matrices, `rankdata` |
| pandas, pyarrow | columnar tables, Parquet artifacts and run results |
| scikit-learn | `CountVectorizer` tokenisation for BM25 |
| orjson | fast JSONL parsing/writing |
| PyYAML | taxonomy and proxy-grade resources |
| sentence-transformers, transformers, torch (CPU), huggingface_hub | embedding model (offline at run time; hub only for the one-time download) |
| fastapi, uvicorn, pydantic, python-multipart | API, validation, uploads |
| openpyxl, reportlab | XLSX import/export, PDF report |
| psutil | memory benchmarks |
| httpx | smoke test, FastAPI TestClient |
| pytest, websocket-client (dev) | tests, screenshot tool |
| React, react-router-dom, lucide-react, @fontsource (frontend) | UI, routing, icons, bundled fonts |
| vite, typescript, vitest, testing-library, jsdom (dev) | build, types, UI tests |

## 4. Starting the application

```bash
cd frontend && npm run build && cd ..          # once, or after UI changes
cd backend && ../.venv/Scripts/python -m uvicorn app.main:app --port 8000
```
`app/main.py` puts the project root on `sys.path` (so `import engine` works), builds services in the
lifespan hook, registers library datasets, and serves `frontend/dist` (SPA fallback: unknown non-API paths
return `index.html`). Dev mode: also run `npm run dev` (port 5173, proxies `/api`).

## 5. Engine walkthrough with examples

### 5.1 Build and load an index
```python
from engine.preprocessing.index import build_index
from engine.preprocessing.store import DatasetIndex

meta = build_index("candidates.jsonl", "artifacts/indexes/demo", progress=lambda f, m: print(f, m))
ix = DatasetIndex("artifacts/indexes/demo")
ix.candidates.head()            # one row per candidate (display + sig_* columns)
ix.record(0)                    # full normalised record via byte offset
ix.flags_for(0)                 # integrity findings
```
`build_index` (preprocessing/index.py): fingerprint → stream + normalise (`Normalizer.normalize`) → for each
record append rows to role/skill lists, register text segments in `_TextTable` (dedupe), write the record to
`records.jsonl`, run `check_record` → write Parquet tables → `BM25Index.build(texts, incidence)` → embed
unique segments → `quality.json`, `meta.json`. Cancellation is checked every 2,000 records and between stages.

### 5.2 Parse a JD
```python
from engine.jd.parser import parse_job_description
spec = parse_job_description(open("engine/resources/jobs/sample_senior_ai_engineer.txt", encoding="utf-8").read())
[(r.id, r.importance, r.weight, r.source_text[:40]) for r in spec.requirements]
spec.experience, spec.location, [c.id for c in spec.constraints]
spec.requirements[0].hard = True          # edit like any Pydantic model
```

### 5.3 Score, shortlist, explain
```python
from engine.ranking.scorer import score_pool, ScoringOptions
from engine.explanations.explain import explain_candidate
pool = score_pool(ix, spec)                         # all candidates, ordered
pool.shortlist(25)                                  # first 25 eligible rows
pool.table.query("not eligible")[["candidate_id", "ineligible_reason"]]
e = explain_candidate(ix, pool, spec, pool.table.candidate_id[0])
e["summary"], e["requirements"][0]["evidence"], e["differentiators"]
score_pool(ix, spec, ScoringOptions(disabled_components=frozenset({"semantic"})))   # ablation
```

### 5.4 Inside `score_pool` (ranking/scorer.py), in order
1. Title relevance per role and current title (`features/titles.py`); recency; career relevance; relevant
   years; skill credibility; per-role trust → `RoleContext`.
2. `TextMatcher(ix)` lower-cases unique texts once; query vectors for every requirement + focus + anchors are
   encoded with `encode_queries` (memoised).
3. `requirement_evidence` per requirement (features/evidence.py) → coverage, skill/text/signal parts, best
   skill row, best role row. Auxiliary concepts (production, CV, speech, NLP, …) are computed the same way
   for constraint detection.
4. Semantic, lexical (BM25 percentile), experience, engagement, logistics components.
5. Weighted sum → constraint factors (`features/constraints.py` detectors keyed by constraint id) → hard
   gates → integrity → evidence completeness → sort → `rank`.
Key helper: `best_per_group(group, values, n)` returns the max per candidate and the winning row using one
`lexsort` - used everywhere "best evidence" is needed.

### 5.5 Competition mode
`scripts/competition_rank.py` → fingerprint → reuse/build index → (network blocked) parse JD, score,
`competition_rows` (top 100, score rounded to 6 dp, ties by id) → `write_submission` → `validate_submission`.

## 6. Backend walkthrough

* **Services object** (`main.build_services`): Settings, Database, JobManager, DatasetService, RunService,
  ShortlistService - attached to `app.state.services`; routes fetch it via `services(request)`.
* **Owner**: `Depends(session_owner)` validates `X-Session-Id` (UUID) → owner string; every query filters by
  owner (datasets also show `owner IS NULL` library rows).
* **Jobs** (`services/jobs.py`): `submit(kind, target_id, owner, fn, on_error, on_cancel)` runs `fn(ctx)` in
  a thread; `ctx.progress()` writes throttled progress; `ctx.check()` raises `JobCancelled`.
* **Datasets** (`services/datasets.py`): `save_upload` streams to `data/uploads/<uuid>.<ext>` enforcing the
  size limit; `import_path` resolves and checks `is_relative_to(allowed_dir)`; `start_index` builds into
  `<fingerprint>.building` then renames (atomic-ish; a failed build leaves no half index).
* **Runs** (`services/runs.py`): `create` → job → `score_pool` → `_result_table` (shortlist + held rows +
  display columns + relevant skills + assessment mean + flag codes + must-haves met) → Parquet. `query`
  implements search/filters/sort/paging in pandas; `explain`/`compare` use the pool LRU.
* **Exports** (`services/exports.py`): CSV (UTF-8 BOM for Excel, `csv_safe` against formula injection), XLSX
  (styled header + "Run" sheet), JSON, JSONL, Parquet, PDF (reportlab; text escaped), competition CSV.

### 6.1 API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | /api/health | status, version, model availability (no session needed) |
| GET | /api/dashboard | datasets, recent runs, activity, totals |
| GET | /api/taxonomy/concepts | capabilities for the requirement editor |
| GET | /api/datasets · /api/datasets/{id} | list · detail (+quality, meta) |
| POST | /api/datasets/upload (multipart `file`) | upload + index |
| POST | /api/datasets/import-path `{path}` | import from an allowed server directory |
| GET | /api/datasets/import-dirs | allowed directories |
| POST | /api/datasets/{id}/reindex · DELETE /api/datasets/{id} | rebuild · delete (not library) |
| GET | /api/jobs/{id} · POST /api/jobs/{id}/cancel | progress · cancel |
| POST | /api/jd/parse `{text, dataset_id?}` · /api/jd/upload (file) | JD → JobSpec |
| GET | /api/jd/presets | bundled JDs |
| GET/POST | /api/runs | list · create `{dataset_id, spec, shortlist_size (null = all eligible), name?}` |
| GET/DELETE | /api/runs/{id} | detail (spec, summary, job) · delete |
| POST | /api/runs/rerun/{id} | re-run with the stored spec |
| GET | /api/runs/{id}/results | `page, page_size, sort, order, q, view=shortlist|held|all, min_score, max_score, min_years, max_years, countries, cities, branches, skills, flags=none|any|critical|warning, min_mandatory` |
| GET | /api/runs/{id}/facets | filter values with counts |
| GET | /api/runs/{id}/candidates/{cid} | full grounded explanation + record |
| POST | /api/runs/{id}/compare `{candidate_ids: 2-6}` | side-by-side |
| POST | /api/runs/{id}/export `{format, scope, candidate_ids?, include_explanations}` | file download |
| POST | /api/runs/{id}/export/competition | validated 100-row CSV |
| GET/POST | /api/shortlists · GET/DELETE /api/shortlists/{id} | list/create · detail/delete |
| POST | /api/shortlists/{id}/items `{candidate_id, note}` · DELETE …/items/{cid} | add/update note · remove |

Errors are always `{"error": {"code", "message"}}` (422 adds `details`).

### 6.2 Database schema (SQLite, `database/db.py`)
`datasets(id, owner NULL=library, name, source_kind, source_path, size_bytes, mtime, fingerprint, status,
n_candidates, index_dir, error, timestamps)` · `jobs(id, owner, kind, target_id, status, progress, message,
error, timestamps)` · `runs(id, owner, dataset_id→datasets ON DELETE CASCADE, name, jd_title, spec_json,
shortlist_size NULL=all, status, job_id, counts, summary_json, error, timestamps)` · `shortlists(id, owner,
run_id→runs CASCADE, name)` · `shortlist_items(shortlist_id→CASCADE, candidate_id, note, PK both)` ·
`activity(owner, kind, message, ref_id, created_at)`. WAL mode; foreign keys on.

## 7. Frontend walkthrough

* **Data loading**: `useAsync(loader, deps)` gives `{data, error, loading, reload}`; `usePoll(fn, ms,
  active)` polls job progress only while something is running; `useDebounced` for search.
* **API client** (`services/api.ts`): adds the session id (generated once with `crypto.randomUUID()` and kept
  in localStorage), converts error JSON to `ApiError`, `uploadDataset` uses XHR for upload progress,
  `download` saves a POSTed file.
* **Pages**: `NewRankingPage` (dataset → JD → `SpecEditor` → shortlist size → `createRun` → navigate);
  `RunPage` (polls the run, then fetches one page of results + facets; `FilterPanel`, `ResultsTable` /
  `ResultCards`, selection → compare / shortlist modal, export menu); `CandidatePage` (explanation);
  `ComparePage`; `HistoryPage`; `ShortlistsPage`; `DatasetsPage` / `DatasetDetailPage`; `DashboardPage`.
* **Rendering rules**: React escapes all text; no `dangerouslySetInnerHTML` anywhere. Never more than one
  page (≤200 rows) of results is rendered; cards fetch their explanation lazily.
* **Sidebar refresh**: `bus.emit("runs")` / `bus.emit("shortlists")` after mutations.
* **Styling**: tokens at the top of `styles/app.css`; components use semantic classes (`card`, `chip ok`,
  `bar signal`, `rank-pill top`).

## 8. Configuration
Environment variables in `backend/app/core/config.py` (table in README). The engine reads
`TALENTSIGNAL_MODEL_DIR`. Calibration constants live in `engine/features/calibration.py`; component weights
default in `engine/jd/spec.py::ComponentWeights`; engagement/logistics/experience sub-weights in
`engine/features/signals.py`; concept vocabulary in `taxonomy.yaml`.

## 9. Testing
```bash
.venv/Scripts/python -m pytest                       # 34 engine + 21 API tests
.venv/Scripts/python -m pytest tests/test_scoring.py -k stuffer -q
cd frontend && npx vitest run                        # 8 workflow tests
python scripts/smoke_test.py                         # live server, real 100K data
python scripts/run_evaluation.py --quick             # evaluation without the adversarial build
```
Engine tests build small indexes from `tests/factories.py` (`embed=False` for speed; `semantic_index` fixture
uses the model when present). API tests run the real app with temporary directories.

## 10. Debugging
* **"Semantic model unavailable" note on a run**: check `engine.retrieval.embeddings.last_error` and the log.
  Make sure `artifacts/models/bge-small-en-v1.5/config.json` exists. Watch for local files that shadow
  stdlib modules (a `profile.py` next to a script broke torch's import once - see DEVELOPMENT_LOG).
* **Why is candidate X ranked here?** `explain_candidate(...)["components"]`, then
  `pool.evidence[req_id].best_role_row[idx]` → `ix.roles.iloc[row]`.
* **Slow scoring?** `python -m cProfile` around `score_pool`; typical hotspots are per-row Python loops -
  move work to unique texts or vectorise.
* **Index looks stale**: the directory name is the file fingerprint; delete the directory to force a rebuild.
* **Job stuck**: `GET /api/jobs/{id}`; jobs running during a restart are marked failed at start-up.

## 11. Common errors
| Symptom | Cause / fix |
|---|---|
| 400 invalid_session | Missing/invalid `X-Session-Id`; the UI sets it automatically |
| 409 dataset_not_ready | Index still building - wait for status `ready` |
| 413 file_too_large | Raise `TALENTSIGNAL_MAX_UPLOAD_MB` or import by path |
| 403 path_not_allowed | Add the directory to `TALENTSIGNAL_IMPORT_DIRS` |
| 422 not_enough_candidates (competition) | Fewer than 100 eligible candidates in the pool |
| `IndexNotFound: incompatible engine version` | Index format changed; re-index |
| pip pulls CUDA torch | Install the CPU wheel first (README) |
| Frontend 404 on refresh in dev | Use `npm run dev` (Vite handles SPA routes) or build and use the backend |

## 12. Making common changes
* **New capability**: add a concept to `taxonomy.yaml` (skills, phrases, semantic sentence). The parser and
  the requirement editor pick it up automatically.
* **New role family**: add `title_patterns` (order matters) and affinities.
* **New score component**: compute it in `score_pool`, add it to `COMPONENTS`, `ComponentWeights`, the
  explanation labels, `frontend/src/types/api.ts`, and the evaluation ablation list.
* **New integrity check**: add to `integrity/checks.py` with a severity and evidence dict, then a test.
