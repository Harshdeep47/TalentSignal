# Engineering Decisions and Alternatives

Every system is a set of trade-offs. This part analyses the major decisions. **Source labels:** "Documented" means the reason is recorded in the repository at the time of the decision (README, `DEVELOPMENT_LOG.md`, `docs/ARCHITECTURE.md`, code docstrings). "Engineering rationale" means a reasonable justification written for this book, not a recorded historical reason.

## Decision summary

| # | Decision | Chosen | Main alternative | Source |
|---|---|---|---|---|
| 1 | Engine/API separation | Engine as a plain library | Logic inside API handlers | Documented |
| 2 | Backend framework | FastAPI + Pydantic | Flask, Django | Documented (stack chosen by the project brief); rationale below |
| 3 | Persistence | SQLite + Parquet files | PostgreSQL, a document DB | Documented |
| 4 | Background work | Thread pool in-process | Celery/RQ + Redis, separate worker processes | Documented |
| 5 | JD understanding | Rule-based parser + human review | LLM extraction | Documented |
| 6 | Semantic model | bge-small-en-v1.5 on unique segments, offline | Larger models, hosted APIs, cross-encoders | Documented (measurements) |
| 7 | Lexical model | BM25 (sparse) | TF-IDF cosine (reference), none | Documented |
| 8 | Scoring model | Weighted, bounded evidence components | Learning-to-rank | Documented |
| 9 | Missing data | Neutral (missing-aware means) | Impute zeros / means | Documented |
| 10 | Disqualifiers | Visible policies (ignore/penalise/exclude) | Hidden multipliers | Documented |
| 11 | Frontend | React + TypeScript + Vite, no UI kit, no global store | Streamlit, Next.js, component library, Redux | Documented (stack from brief); details rationale |
| 12 | Result paging | Server-side pages from Parquet | Send all rows, virtual scrolling | Documented |
| 13 | Identity | Per-browser session id | Real authentication | Documented as a limitation |
| 14 | Packaging | Single process serves API + built SPA | Separate frontend hosting / containers | Engineering rationale |

## 1. Engine as an independent library

**Selected:** `engine/` has no web imports; backend, scripts, tests and competition mode call it.
**Why:** one implementation of the algorithm for every entry point; fast unit tests without HTTP; competition mode must run without a server.
**Alternatives:** logic in route handlers (simpler at first) or a separate ranking microservice (independent scaling).
**Trade-off:** an extra boundary to design (the `JobSpec` model, the `ScoredPool` result).
**When the alternative is better:** a microservice when ranking must scale separately from the API or be written in another language.

## 2. FastAPI and Pydantic

**Selected:** FastAPI for routing, dependency injection (`Depends(session_owner)`) and automatic validation; Pydantic models shared with the engine (`JobSpec`).
**Advantages:** type hints drive validation and documentation; one validation model end to end; good performance.
**Disadvantages:** async features are mostly unused (the heavy work is in threads); Pydantic validation of large nested specs costs a little time.
**Alternatives:** Flask (simpler, more manual validation), Django (batteries included - ORM, admin, auth - heavier than needed).
**When the alternative is better:** Django if user accounts, permissions and an admin interface become central requirements.

## 3. SQLite plus Parquet

**Selected:** SQLite for small relational records; Parquet/NumPy files for large data.
**Advantages:** zero installation and operations; WAL mode supports concurrent reads; columnar files are ideal for vectorised scoring and fast filtering.
**Disadvantages:** a single writer; no network access for multiple servers; no transaction across the database and the Parquet file (Part 5 lists the consequence).
**Alternative:** PostgreSQL (concurrent writers, replication, row-level security). **Better when** several server instances or many concurrent users must share state.

## 4. In-process thread pool for jobs

**Selected:** `ThreadPoolExecutor(max_workers=2)` with job state in SQLite.
**Why:** NumPy, SciPy and PyTorch release Python's global interpreter lock (GIL) during heavy operations, so threads parallelise well; threads share the in-memory `IndexCache`.
**Disadvantages:** jobs die with the server process (they are marked failed at restart); work cannot be spread over machines; a CPU-heavy pure-Python step would block other threads.
**Alternative:** a task queue (Celery or RQ with Redis) and worker processes. **Better when** jobs must survive restarts, run on other machines, or be retried automatically.

## 5. Rule-based JD parser with human review

**Selected:** heading classification, a taxonomy of concepts, regex extractors, and a mandatory review screen.
**Advantages:** offline, free, deterministic, every extraction traceable to a sentence; no risk of an LLM inventing requirements.
**Disadvantages:** limited to concepts in the taxonomy; JD styles that ignore headings are parsed less well; granularity quirks (Book 1, Part 5).
**Alternative:** LLM-based extraction. **Better when** JDs are very diverse and a human review step is kept anyway; the existing `JobSpec` and review UI would accept an LLM's output unchanged.

## 6. Small local embedding model on unique segments

**Selected:** bge-small-en-v1.5 (MIT, 384 dimensions), offline, embedding only unique segments at index time.
**Documented measurements:** about 65 long texts per second on this CPU; 5,802 unique segments embedded in 108 s; calibration windows measured (unrelated 0.41-0.55, matches 0.75-0.85).
**Alternatives:** larger models (better quality, slower), hosted embedding APIs (fast, but send candidate data outside and need network), cross-encoders (most accurate pairwise relevance, far too slow for 100,000 candidates per query).
**When better:** a cross-encoder to re-rank only the top few hundred candidates is a sensible future addition, evaluated with the same harness.

## 7. BM25 instead of TF-IDF

**Selected:** BM25 with \(k_1 = 1.2\), \(b = 0.75\), unigrams and bigrams, English stop words, as a percentile component of 5%.
**Why:** saturation and length normalisation; a standard, well-understood baseline.
**Honest finding:** removing it did not change this JD's top 100; it is kept for custom requirements whose words are outside the taxonomy.

## 8. Weighted evidence model instead of learning-to-rank

**Selected:** seven interpretable components and recruiter-editable weights.
**Why (documented):** there are no relevance labels; training a model on the project's own proxy labels would only teach the model those heuristics.
**Alternative:** a learned ranker (for example LightGBM with a LambdaMART objective) over the same features. **Better when** real outcome or feedback labels exist (shortlisted, interviewed, hired); the component columns are already a feature matrix.

## 9-10. Neutral missing data and visible policies

These are fairness and accountability decisions (Book 1, Part 10). Their costs: neutral missing data means a profile with few signals is not rewarded for completeness - which is intended; visible policies give recruiters power to make harsh choices, which is why defaults are moderate and every choice is shown in the run's spec.

## 11. React, TypeScript, Vite - and no UI kit or global store

**Selected:** React 18 + TypeScript + Vite; hand-written CSS design system; lucide icons; no Redux.
**Engineering rationale:** the reference project's Streamlit UI could not provide multi-page navigation, server-side paging, comparison and fine-grained state; TypeScript catches API-shape mistakes; Vite builds in seconds; a component library would have imposed a generic look; no data needed to be shared across distant components, so a global store would add indirection without benefit.
**When the alternative is better:** a component library when many developers need consistent widgets quickly; a store (or a data-fetching cache such as TanStack Query) when many pages share and mutate the same server data.

## 12-14. Paging, identity, packaging

- **Server-side paging** instead of shipping all rows: constant browser memory, ~150-270 ms queries on 99,932 rows. Virtual scrolling would allow smooth scrolling of all rows but needs all rows in the browser.
- **Session ids instead of authentication:** acceptable for local use and demos; a known blocker for public hosting.
- **One process serves everything:** `uvicorn` serves the API and the built SPA from `frontend/dist`, so deployment is a single command. **Better alternative at scale:** static files on a CDN, the API behind a reverse proxy, workers separate.
