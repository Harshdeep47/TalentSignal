# The Complete Architecture

An *architecture* is the answer to "what are the big pieces, what is each piece responsible for, and how do they talk to each other?". This part gives you that map. Keep it in mind for the rest of the book; every later part zooms into one box of these diagrams.

## The three layers

TalentSignal is split into three layers, each in its own folder:

| Layer | Folder | Language | Responsibility |
|---|---|---|---|
| **Frontend** | `frontend/src/` | TypeScript + React | Everything the recruiter sees and clicks: pages, tables, forms, charts |
| **Backend** | `backend/app/` | Python + FastAPI | A web server: receives requests, stores runs and shortlists, runs long jobs in the background, returns JSON |
| **Engine** | `engine/` | Python (NumPy, pandas, scikit-learn, sentence-transformers) | The intelligence: reading candidate files, understanding the job, scoring, explaining, evaluating |

The most important architectural rule is **the engine knows nothing about the web**. It is a plain Python library. The backend *calls* the engine; the engine never imports anything from the backend. This rule is why the same engine can be used by the web app, by command-line scripts, by the competition mode and by the evaluation harness.

```mermaid
flowchart TB
    subgraph Browser["Recruiter's browser"]
        UI["React single-page app<br/>frontend/src"]
    end
    subgraph Server["Python process (uvicorn)"]
        API["FastAPI routes<br/>backend/app/api/routes.py"]
        SVC["Services<br/>datasets · runs · shortlists · exports · jobs"]
        DB[("SQLite<br/>data/talentsignal.sqlite3")]
        ENG["Engine library<br/>engine/"]
    end
    subgraph Disk["Files on disk"]
        IDX[("Dataset indexes<br/>artifacts/indexes/&lt;fingerprint&gt;/")]
        RUNS[("Run results<br/>artifacts/runs/&lt;run_id&gt;.parquet")]
        MODEL[("Embedding model<br/>artifacts/models/bge-small-en-v1.5")]
        SRC[("Candidate files<br/>uploads or allowed folders")]
    end
    CLI["Command-line scripts<br/>scripts/*.py"]
    UI -- "HTTP + JSON /api" --> API
    API --> SVC
    SVC --> DB
    SVC --> ENG
    CLI --> ENG
    ENG --> IDX
    ENG --> MODEL
    SVC --> RUNS
    ENG --> SRC
```
<p class="caption">Figure 2.1 - Overall architecture. Boxes are components; cylinders are stored data. Arrows point from the caller to what it uses.</p>

Read the figure from top to bottom. The browser only ever talks to the API over HTTP. The API delegates all real work to *services*. Services store small structured facts (who ran what, when) in SQLite, and call the engine for heavy work. The engine reads candidate files, writes and reads indexes, and loads the embedding model. Command-line scripts bypass the web entirely and call the engine directly.

## Each component: responsibility, inputs, outputs

| Component | Key files | Input | Output | Talks to |
|---|---|---|---|---|
| React app | `frontend/src/App.tsx`, `pages/*.tsx` | User clicks, typed JD text, uploaded files | Pages; HTTP requests | Backend API only |
| API routes | `backend/app/api/routes.py` | HTTP requests with `X-Session-Id` | JSON responses, files | Services |
| Dataset service | `backend/app/services/datasets.py` | Uploaded file stream or a server path | Dataset record; background index job | Engine (`build_index`), SQLite |
| Run service | `backend/app/services/runs.py` | Dataset id, `JobSpec`, shortlist size | Run record; result table (Parquet); explanations | Engine (`score_pool`, `explain_candidate`), SQLite |
| Export service | `backend/app/services/exports.py` | Run id, format | CSV / XLSX / JSON / JSONL / Parquet / PDF bytes | Run service, engine competition module |
| Job manager | `backend/app/services/jobs.py` | A function to run in the background | Job record with progress and status | SQLite |
| Database | `backend/app/database/db.py` | SQL statements | Rows | File `data/talentsignal.sqlite3` |
| Ingestion | `engine/ingestion/*.py` | A candidate file (JSONL, JSON, CSV, XLSX, Parquet) | Normalised records + validation issues | - |
| Index builder | `engine/preprocessing/index.py` | Candidate file | Index directory (tables, BM25, embeddings, quality report) | Ingestion, integrity, retrieval |
| JD parser | `engine/jd/parser.py` | JD text | `JobSpec` (editable requirements and settings) | Taxonomy |
| Scorer | `engine/ranking/scorer.py` | Index + `JobSpec` | `ScoredPool` (every candidate scored and ordered) | Features, retrieval |
| Explainer | `engine/explanations/explain.py` | Scored pool + candidate id | Explanation dictionary | Validator |

## How the components interact

The next diagram shows *which code calls which code* inside the Python process. It is a dependency picture: an arrow from A to B means "A imports or calls B".

```mermaid
flowchart LR
    R["api/routes.py"] --> DS["services/datasets.py"]
    R --> RS["services/runs.py"]
    R --> SL["services/shortlists.py"]
    R --> EX["services/exports.py"]
    R --> JP["engine/jd/parser.py"]
    DS --> JM["services/jobs.py"]
    RS --> JM
    DS --> BI["engine/preprocessing/index.py"]
    RS --> SC["engine/ranking/scorer.py"]
    RS --> XP["engine/explanations/explain.py"]
    EX --> RS
    EX --> CP["engine/ranking/competition.py"]
    BI --> IN["engine/ingestion/*"]
    BI --> IC["engine/integrity/checks.py"]
    BI --> BM["engine/retrieval/bm25.py"]
    BI --> EM["engine/retrieval/embeddings.py"]
    SC --> FE["engine/features/*"]
    SC --> BM
    SC --> EM
    XP --> VA["engine/explanations/validator.py"]
    CP --> XP
    JP --> TX["engine/taxonomy.py"]
    FE --> TX
```
<p class="caption">Figure 2.2 - Component interaction (import/call dependencies). Backend modules are on the left, engine modules on the right. No engine module points back to the backend.</p>

## How the frontend talks to the backend

The frontend and backend communicate only through **HTTP requests that carry JSON**. Every request includes a header named `X-Session-Id` containing a random identifier the browser generated the first time it opened the app (stored in the browser's `localStorage`). The backend uses that identifier to keep each browser's runs and shortlists separate. It is *not* a login system - Part 10 explains why that matters.

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser (api.ts)
    participant F as FastAPI (routes.py)
    participant S as RunService
    participant J as JobManager thread
    participant E as Engine (score_pool)
    B->>F: POST /api/runs {dataset_id, spec, shortlist_size} + X-Session-Id
    F->>S: create(owner, dataset_id, spec, size)
    S->>J: submit("rank", work)
    S-->>F: run row (status "queued")
    F-->>B: 201 Created {id, status}
    J->>E: score_pool(index, spec)
    E-->>J: ScoredPool
    J->>S: save result table (Parquet), status "ready"
    loop every second while running
        B->>F: GET /api/runs/{id}
        F-->>B: {status, job.progress}
    end
    B->>F: GET /api/runs/{id}/results?page=1
    F-->>B: {total, items[...]}
```
<p class="caption">Figure 2.3 - Frontend-to-backend communication when the recruiter starts a ranking. The request returns immediately; the heavy work happens in a background thread while the browser polls for progress.</p>

The key idea is **asynchronous work**. Scoring 100,000 candidates takes a few seconds; building an index takes about two minutes. A web request should not hang that long, so the backend answers immediately with a run whose status is `queued`, does the work in a background thread, and the browser asks for the status once a second (*polling*) until it becomes `ready`.

## The complete request lifecycle

What happens, step by step, when the browser asks for one page of results? This is the most frequent request in the application.

```mermaid
flowchart TD
    A["Browser: api.results(runId, query)<br/>frontend/src/services/api.ts"] --> B["HTTP GET /api/runs/{id}/results?page=1&countries=India"]
    B --> C["CORS + security-header middleware<br/>backend/app/main.py"]
    C --> D["Route run_results()<br/>validates query parameters"]
    D --> E["Depends(session_owner)<br/>checks X-Session-Id is a UUID"]
    E --> F["RunService.query()"]
    F --> G{"Result table in<br/>memory cache?"}
    G -- yes --> I["Filter + sort + slice one page<br/>(pandas)"]
    G -- no --> H["Read artifacts/runs/&lt;id&gt;.parquet"] --> I
    I --> J["_row_json(): convert NumPy values to JSON-safe values"]
    J --> K["JSON response {total, page, page_size, items}"]
    K --> L["React state update → table re-renders"]
    D -. invalid input .-> X["422 {error: {code, message}}"]
    E -. bad session .-> Y["400 invalid_session"]
```
<p class="caption">Figure 2.4 - Lifecycle of a results request. Dotted arrows are error paths; every error returns the same JSON shape.</p>

## How candidate data flows through the system

A candidate file travels a long way before a recruiter sees a ranked row. The next diagram follows one file from upload to screen.

```mermaid
flowchart LR
    U["Upload or<br/>server path"] --> S1["Stream to disk<br/>save_upload()"]
    S1 --> S2["Fingerprint<br/>BLAKE2b of every byte"]
    S2 --> S3["Read records one by one<br/>iter_records()"]
    S3 --> S4["Normalise + validate<br/>Normalizer.normalize()"]
    S4 --> S5["Integrity checks<br/>check_record()"]
    S4 --> S6["Columnar tables<br/>candidates · roles · skills · texts"]
    S6 --> S7["BM25 index<br/>(sparse matrix)"]
    S6 --> S8["Embeddings of unique<br/>text segments"]
    S5 --> IX[("Index directory")]
    S6 --> IX
    S7 --> IX
    S8 --> IX
    IX --> SC["score_pool()"]
    SC --> RT[("Run result table")]
    RT --> UI["Results page"]
```
<p class="caption">Figure 2.5 - Candidate data flow. Everything left of the index directory happens once per file; everything right of it happens once per ranking run.</p>

The split in Figure 2.5 is the **precompute / rank** pattern. Expensive work that does not depend on the job (parsing, cleaning, tokenising, embedding) happens once per candidate file and is saved. Work that depends on the job (scoring) is cheap because it reuses that saved work. On the reference machine, the one-time index build took **137 seconds**; scoring the same 100,000 candidates against a job takes about **2.9 seconds**.

## The ranking pipeline at a glance

Part 6 explains every box in detail. Here is the overview.

```mermaid
flowchart TD
    JD["Job description text"] --> P["parse_job_description()"] --> SPEC["JobSpec<br/>(reviewed and edited by recruiter)"]
    IX[("Dataset index")] --> CTX
    SPEC --> CTX["Title relevance, recency,<br/>trust, credibility per role"]
    CTX --> REQ["Requirement evidence<br/>skills ⊕ career text ⊕ signals<br/>(noisy-OR per requirement)"]
    CTX --> RF["Role fit"]
    SPEC --> SEM["Semantic similarity<br/>(embeddings)"]
    SPEC --> LEX["Lexical relevance<br/>(BM25 percentile)"]
    IX --> EXP["Experience"]
    IX --> ENGG["Engagement"]
    IX --> LOG["Logistics"]
    REQ & RF & SEM & LEX & EXP & ENGG & LOG --> W["Weighted sum<br/>Σ w_c · component_c"]
    W --> CF["× factors of declared conditions<br/>(policy = penalise)"]
    CF --> EL["Eligibility: hard requirements,<br/>excluded conditions, critical integrity"]
    EL --> ORD["Deterministic ordering → ranks"]
    ORD --> OUT["ScoredPool → shortlist + explanations"]
```
<p class="caption">Figure 2.6 - Ranking pipeline overview. Seven components are computed for every candidate, combined by a weighted sum, adjusted by declared policies, filtered for eligibility, then ordered.</p>

## Where data is stored, and why in different places

TalentSignal uses three kinds of storage, each chosen for what it holds:

| Storage | What it holds | Why this kind |
|---|---|---|
| SQLite database (`data/talentsignal.sqlite3`) | Datasets, jobs, runs, shortlists, activity - small structured records | Relationships (a shortlist belongs to a run), transactions, zero setup |
| Index directory (`artifacts/indexes/<fingerprint>/`) | Normalised records, Parquet tables, BM25 matrix, embeddings, quality report | Large numeric/columnar data read in bulk by NumPy and pandas |
| Run results (`artifacts/runs/<run_id>.parquet`) | One row per shortlisted (or held) candidate with all component scores | Fast columnar filtering and sorting of up to ~100,000 rows |

The index directory is named after the **fingerprint** of the candidate file - a hash of every byte. Two consequences follow: an identical file is never indexed twice, and a file that changed even by one byte gets a new index instead of silently reusing a stale one.

## How exports fit in

Exports are produced on demand from the run's result table: CSV, XLSX, JSON, JSONL and Parquet copy rows; the PDF report adds explanation summaries for the top candidates; the *competition* export produces exactly 100 rows in the original challenge format and validates them before returning. Part 11 traces an export end to end, and Book 2 documents each format.

!!! note "Summary of Part 2"
    Three layers (frontend, backend, engine) with a strict rule that the engine is a plain library. Communication is HTTP + JSON with a session header. Heavy work runs in background jobs while the browser polls. Data is processed once per file (index) and cheaply per job (scoring). Storage is split by purpose: SQLite for records, Parquet/NumPy files for bulk data.
