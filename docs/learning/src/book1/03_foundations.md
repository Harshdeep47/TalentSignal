# Programming Foundations for Reading the Code

This part teaches the programming ideas you need to read TalentSignal's source. It is not a general programming course: every concept is introduced because the project uses it, and every example is either taken from the project or written in its style. If you already program in Python and TypeScript, skim the tables and move on.

## Python in five minutes: values, variables and functions

A *program* is a list of instructions. Python executes them top to bottom. A **variable** is a name for a value; a **function** is a named, reusable block of instructions that takes inputs (*parameters*) and returns an output.

```python
# runnable
def notice_fit(notice_days, ideal_max=30):
    """Return 1.0 when the notice period is within the ideal, less otherwise."""
    if notice_days <= ideal_max:
        return 1.0
    return 0.7

print(notice_fit(15))   # 1.0
print(notice_fit(90))   # 0.7
```

The real `notice_fit` in `engine/features/signals.py` is more detailed (it decays smoothly and works on thousands of candidates at once), but the shape is the same: inputs in, a number between 0 and 1 out. Most of TalentSignal's scoring is built from small functions like this.

!!! tip "Docstrings"
    The text in triple quotes right under `def` is a *docstring* - documentation attached to the function. TalentSignal uses docstrings heavily to explain *why* code exists; read them first when you open a file.

## Type hints

Python does not require you to declare types, but you may *annotate* them. These **type hints** are not enforced at run time; they document intent and let tools catch mistakes.

```python
def title_relevance(title: str, spec: "JobSpec", tax: "Taxonomy") -> float:
    ...
```

Read this as: "`title_relevance` takes a string, a `JobSpec` and a `Taxonomy`, and returns a float". You will also see `list[str]` (a list of strings), `dict[str, float]` (a dictionary from strings to floats), `str | None` (a string or nothing), and `np.ndarray` (a NumPy array).

## The four core data structures

| Structure | Python syntax | Ordered? | Mutable? | Lookup by | Used in TalentSignal for |
|---|---|---|---|---|---|
| list | `[1, 2, 3]` | yes | yes | position | career history roles, requirement lists |
| tuple | `(1, 2)` | yes | no | position | fixed pairs such as `(lo, hi)` calibration bounds |
| dict | `{"a": 1}` | insertion order | yes | key | a candidate record, JSON objects, lookup tables |
| set | `{"a", "b"}` | no | yes | membership | "which skills does the requirement accept?" |

The most important is the **dictionary** (often called a *hash map*). Looking up a key is fast regardless of size because Python computes a *hash* of the key and jumps almost directly to it. TalentSignal uses this constantly, for example `DatasetIndex.id_to_idx` maps each candidate ID to its row number so a candidate can be found among 100,000 in constant time.

```python
# runnable
skills = [{"name": "Python", "proficiency": "expert"}, {"name": "FAISS", "proficiency": "advanced"}]
wanted = {"faiss", "pinecone", "milvus"}            # a set: fast membership tests
matches = [s for s in skills if s["name"].lower() in wanted]
print(matches)                                        # [{'name': 'FAISS', 'proficiency': 'advanced'}]
```

The last line before `print` is a **list comprehension**: "make a list of `s` for each `s` in `skills` where the condition holds". You will see comprehensions everywhere in the code.

## Classes and objects

A **class** is a blueprint that bundles data (*attributes*) with functions that act on it (*methods*). An **object** is one instance built from the blueprint. TalentSignal uses classes for things that hold state:

- `DatasetIndex` (`engine/preprocessing/store.py`) holds the path of an index and lazily loads its tables.
- `BM25Index` (`engine/retrieval/bm25.py`) holds a sparse matrix and knows how to score a query.
- `JobManager` (`backend/app/services/jobs.py`) holds a thread pool and the cancel flags of running jobs.

Two special kinds of class appear often:

- **Dataclasses** (`@dataclass`) automatically generate the boring parts of a class from field declarations. `ScoredPool` and `RoleContext` in the engine are dataclasses: they are mostly containers of arrays.
- **Pydantic models** (classes that inherit from `BaseModel`) add *validation*: when you build one, every field is checked against its declared type and constraints. `JobSpec` and `Requirement` (`engine/jd/spec.py`) are Pydantic models, so a weight of 7 or a negative minimum coverage is rejected automatically.

```python
from pydantic import BaseModel, Field

class Requirement(BaseModel):            # excerpt (simplified from engine/jd/spec.py)
    id: str
    label: str
    importance: str = "preferred"
    weight: float = Field(1.0, ge=0.0, le=1.0)   # must lie between 0 and 1
```

## Modules and packages

A **module** is one `.py` file; a **package** is a folder of modules with an `__init__.py` file. `import` brings code from one module into another:

```python
from engine.ranking.scorer import score_pool       # function score_pool from engine/ranking/scorer.py
```

The dotted path mirrors the folder path. The backend adds the project root to Python's search path at start-up (`backend/app/main.py`) precisely so that `import engine` works.

## JSON and JSONL

**JSON** (JavaScript Object Notation) is a text format for structured data: objects in `{}`, arrays in `[]`, strings in double quotes, numbers, `true`/`false`, and `null`. It maps directly onto Python dicts, lists, strings, numbers, booleans and `None`.

**JSONL** (JSON Lines) puts one JSON object on each line. The reference candidate file is JSONL: 100,000 lines, one candidate per line. JSONL matters for scale: you can read **one line at a time** without loading the whole 465 MB file into memory. A normal JSON array cannot be read that way - you have to parse it whole.

```python
# runnable
import io, json
jsonl = io.StringIO('{"candidate_id": "CAND_0000001"}\n{"candidate_id": "CAND_0000002"}\n')
for line in jsonl:                      # one line at a time: memory use stays small
    record = json.loads(line)
    print(record["candidate_id"])
```

TalentSignal uses the faster `orjson` library instead of the standard `json` module, but the idea is identical (`engine/ingestion/readers.py`).

## Files and streaming

Opening a file and iterating over it yields one line at a time. For binary data (uploads, hashing) the code reads fixed-size *chunks*:

```python
import hashlib

def file_fingerprint(path):                         # excerpt (engine/ingestion/fingerprint.py, simplified)
    h = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as f:                     # "rb" = read bytes
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):   # 4 MB at a time
            h.update(chunk)
    return h.hexdigest()
```

The `with` statement guarantees the file is closed even if an error happens. `iter(callable, sentinel)` keeps calling `f.read(...)` until it returns the empty bytes `b""` (end of file).

## Exceptions and error handling

When something goes wrong Python *raises* an **exception**. Code can *catch* it with `try`/`except` and respond. TalentSignal follows two rules:

1. **Never hide failures.** For example, when the embedding model fails to load, `get_embedder` records the error in `last_error` and logs it instead of silently returning nothing (this was added after a real silent failure; see the development log).
2. **Convert internal errors to clear user messages.** The backend defines `AppError(status, code, message)` in `backend/app/core/errors.py`; every service raises it for expected problems (file too large, dataset not ready), and a single handler turns it into the JSON `{"error": {"code", "message"}}`.

```python
# runnable
class AppError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

def check_size(n_bytes, limit):
    if n_bytes > limit:
        raise AppError(413, "file_too_large", f"File exceeds the {limit} byte limit.")

try:
    check_size(5_000, 1_000)
except AppError as e:
    print(e.status, e.code, e.message)
```

## NumPy: thinking in whole columns

NumPy is the library that makes scoring 100,000 candidates take seconds rather than hours. Its central idea is **vectorisation**: instead of looping over candidates one by one in Python, you write one expression that operates on whole arrays at once, and NumPy runs the loop in fast compiled code.

```python
# runnable
import numpy as np
years = np.array([2.0, 6.5, 12.0])              # three candidates
in_band = (years >= 5) & (years <= 9)            # element-wise comparison -> [False True False]
score = np.where(in_band, 1.0, 0.5)              # pick 1.0 where in band, else 0.5
print(score)                                     # [0.5 1.  0.5]
```

Almost every function in `engine/features/` works this way. When you read them, imagine each variable as a whole column of a spreadsheet, not a single number.

**pandas** builds on NumPy with *DataFrames* - tables with named columns (like a spreadsheet in memory). TalentSignal stores candidates, roles and skills as DataFrames saved in **Parquet**, a compact columnar file format.

## APIs, HTTP and REST

An **API** (Application Programming Interface) is a defined way for one program to ask another for something. A **web API** does this over **HTTP**, the protocol browsers use. Every HTTP request has:

| Part | Example in TalentSignal |
|---|---|
| Method (verb) | `GET` (read), `POST` (create/act), `DELETE` (remove) |
| URL path | `/api/runs/3f2a.../results` |
| Query parameters | `?page=2&countries=India` |
| Headers | `X-Session-Id: 6d1c...` , `Content-Type: application/json` |
| Body (optional) | `{"dataset_id": "...", "spec": {...}, "shortlist_size": 100}` |

The response carries a **status code** (`200` OK, `201` Created, `204` No Content, `400` bad request, `404` not found, `409` conflict, `413` too large, `415` unsupported type, `422` invalid input, `500` server error) and usually a JSON body.

**REST** (Representational State Transfer) is a style of designing web APIs around *resources* named by URLs: `/api/runs` is the collection of runs, `/api/runs/{id}` one run, `/api/runs/{id}/results` that run's results. TalentSignal follows this style, with a few action endpoints such as `POST /api/runs/{id}/compare` where an action does not fit neatly into create/read/delete.

**FastAPI** is the Python framework that turns decorated functions into endpoints:

```python
@router.get("/runs/{run_id}")                       # excerpt (backend/app/api/routes.py)
def get_run(request: Request, owner: Owner, run_id: str):
    return services(request).runs.get(run_id, owner)
```

FastAPI reads the type hints to validate inputs and converts the returned dict to JSON.

## SQL and relational databases

A **relational database** stores data in **tables** of rows and columns. **SQL** (Structured Query Language) asks questions of those tables. TalentSignal uses **SQLite**, a database that lives in a single file and needs no server.

```sql
SELECT id, name, status FROM datasets WHERE owner IS NULL OR owner = ? ORDER BY created_at DESC;
```

Key ideas used in the project:

- **Primary key** - a column whose value uniquely identifies a row (`id`).
- **Foreign key** - a column that refers to another table's primary key (`runs.dataset_id` → `datasets.id`). With `ON DELETE CASCADE`, deleting a dataset automatically deletes its runs.
- **Parameterised queries** - the `?` placeholders. Values are passed separately, never pasted into the SQL text, which prevents *SQL injection* attacks.
- **Transactions** - a group of changes that either all happen or none happen.

Book 2, Part 5 shows the full schema and an entity-relationship diagram.

## Asynchronous work and background jobs

Some work takes a long time. If the web server did it *inside* the request, the browser would wait (and might time out). TalentSignal therefore:

1. Responds to the request immediately with a job or run whose status is `queued`.
2. Runs the work in a **background thread** managed by `JobManager` (a *thread* is a second line of execution inside the same program).
3. Lets the browser **poll** - ask again every second - until the status is `ready`.

In the frontend you will also see `async`/`await`: a function marked `async` can pause at `await` while waiting for a network response without freezing the page.

## React fundamentals

**React** is a JavaScript library for building user interfaces from **components** - functions that return a description of what should appear on screen. Components receive inputs called **props** and keep private **state**. When state changes, React re-runs the component and updates the page.

```tsx
function RankPill({ rank }: { rank: number }) {          // excerpt (frontend/src/components/ui.tsx)
  if (!rank) return <span className="rank-pill" title="Held for review">-</span>;
  return <span className={`rank-pill ${rank <= 10 ? "top" : ""}`}>{rank}</span>;
}
```

The syntax mixing HTML-like tags and code is **JSX**. `className` is HTML's `class`. Curly braces `{...}` insert JavaScript values.

Two React **hooks** appear everywhere:

- `useState` - remember a value between renders (`const [page, setPage] = useState(1)`).
- `useEffect` - run code after rendering, for example to fetch data when the page number changes.

TalentSignal wraps data loading in its own hook, `useAsync` (`frontend/src/hooks/useAsync.ts`), which returns `{data, error, loading, reload}` so every page handles loading and error states the same way.

## TypeScript fundamentals

**TypeScript** is JavaScript with types. The compiler checks that, for example, a `ResultRow` really has an `overall` number before the code ever runs. All the shapes of data returned by the API are declared in one file, `frontend/src/types/api.ts`:

```ts
export interface ResultRow {        // excerpt
  rank: number;
  candidate_id: string;
  overall: number;
  relevant_skills: string[];
  flag_codes: string[];
}
```

If the backend renamed `overall`, the TypeScript build would fail everywhere the old name is used - a cheap, early warning.

## State management in this project

"State management" means deciding where data lives in the frontend and who may change it. TalentSignal deliberately keeps it simple:

| State | Where it lives | Example |
|---|---|---|
| Server data | fetched per page with `useAsync`, kept in component state | the run, one page of results |
| UI choices | `useState` in the page | current filters, table vs card layout, selected rows |
| Session identity | browser `localStorage` | `talentsignal.session` |
| Cross-page refresh signal | a tiny event bus (`bus.emit("runs")`) | the sidebar reloads recent runs after a new run |

There is no global store library (such as Redux) because no data needs to be shared across many unrelated components. That is a deliberate simplicity choice; Book 2 discusses when it would change.

## Virtual environments and dependencies

A **dependency** is someone else's code your project uses (NumPy, FastAPI, React). Projects pin exact versions so they behave the same on every machine:

- Python dependencies: `requirements.txt` (runtime) and `requirements-dev.txt` (tests and tools).
- JavaScript dependencies: `frontend/package.json` (and the exact resolved tree in `package-lock.json`).

A **virtual environment** (`.venv/`) is a private folder of Python packages for one project, so different projects cannot break each other. JavaScript's equivalent is the `node_modules/` folder. Both are excluded from version control and recreated from the pinned files.

!!! note "Check yourself"
    You should now be able to read a line such as `wanted = [vocab[s.lower()] for s in req.skills if s.lower() in vocab]` (a list comprehension over a requirement's skills, looking each up in a dictionary) and `np.where(arg >= 0, rows[arg], -1)` (an element-wise choice across a whole array). If either is unclear, re-read the data-structure and NumPy sections.
