# Exercise Hints and Solutions {.appendix}

## Level 1

**1.1 - Trace a number.** UI: `RunPage` → `ResultsTable` (or the candidate page's "Logistics signals" panel). API: `GET /api/runs/{id}/candidates/{cid}` → `RunService.explain` → `explain_candidate` → `_signal_breakdown` reads the `log_*` columns. Engine: `score_pool` calls `logistics_parts(cand, spec, tax)` in `engine/features/signals.py`, which calls `location_fit`, `notice_fit` and `work_mode_fit`; `weighted_available(log_parts, LOGISTICS_WEIGHTS)` combines them; the result is stored as `tbl["logistics"]` and multiplied by the normalised weight in the weighted sum. Inputs come from the `sig_*` columns of `candidates.parquet` written by `build_index`.

**1.2 - Change a default weight.** Edit `engagement: float = Field(0.11, ge=0)` in `ComponentWeights` (`engine/jd/spec.py`) to 0.15. The weights now sum to 1.04, so after normalisation engagement's share is \(0.15/1.04 = 14.4\%\) and every other share shrinks by the factor \(1/1.04\). `test_weights_normalize_and_disable` still passes (it checks that normalised weights sum to 1). The worked example numbers in Book 1, Part 7 would change - the scripts in `docs/learning/build/` regenerate them.

**1.3 - Add a concept.** Add under `concepts:` in `engine/resources/taxonomy.yaml`:

```yaml
graph_ml:
  label: Graph machine learning
  category: ml
  skills: [Graph Neural Networks, PyTorch Geometric]
  phrases: [graph neural network, gnn, knowledge graph embedding]
  semantic: Built graph neural network models over relational or knowledge-graph data.
```

Verify:

```python
from engine.jd.parser import parse_job_description
spec = parse_job_description("ML Engineer\nMust have:\n- Experience with graph neural networks in production\n")
assert any(r.id == "graph_ml" and r.importance == "mandatory" for r in spec.requirements)
```

`load_taxonomy` is cached per process - restart the Python process after editing the YAML.

## Level 2

**2.1 - Filter "open to work".** (1) In `routes.py::run_results` add `open_to_work: bool | None = None` and pass it on. (2) In `RunService.query` add the parameter and `if open_to_work: df = df[df["sig_open_to_work_flag"] == True]`. The column is already in the result table because `DISPLAY_COLS` includes `sig_open_to_work_flag`. (3) In `services/api.ts` add `open_to_work?: boolean` to `ResultQuery`; in `FilterPanel` add a checkbox calling `upd({open_to_work: e.target.checked || undefined})`. (4) Test in `backend/tests/test_api.py`: request `?open_to_work=true` and assert `item["sig_open_to_work_flag"] is True` for every returned item. This works because `_row_json` keeps `sig_*` columns (it only removes `eng_`, `log_` and `exp_` columns and regroups `req_` and `c_` columns).

**2.2 - Export column.** Add `"highest_degree"` to `EXPORT_COLUMNS` in `backend/app/services/exports.py`. It is already a result-table column (from `DISPLAY_COLS`). CSV and XLSX pick it up automatically; `csv_safe` already protects it.

**2.3 - Text summary endpoint.** In `routes.py`:

```python
from fastapi.responses import PlainTextResponse

@router.get("/runs/{run_id}/summary.txt", response_class=PlainTextResponse)
def run_summary_text(request: Request, owner: Owner, run_id: str):
    s = services(request)
    run = s.runs.get(run_id, owner)              # 404 for other sessions
    page = s.runs.query(run_id, owner, page=1, page_size=10)
    lines = [f"{run['jd_title']} - {run['dataset_name']}",
             f"scored {run['n_candidates']}, eligible {run['n_eligible']}"]
    lines += [f"{i['rank']:>3}  {i['candidate_id']}  {i['overall']:.3f}" for i in page["items"]]
    return "\n".join(lines)
```

Ownership comes for free because `RunService.get` filters by owner.

**2.4 - Frontend component.** Inside `RunPage`, after the selection toolbar, render (when `selected.size` is 1-6) a small card mapping selected ids to rows found in `page.items`, each with `<ScoreBar value={row.overall} />`. Note that selected candidates on *other* pages are not in `page.items` - either show only those on the current page or keep a `Map` of selected rows when selecting.

## Level 3

**3.1 - Certifications as weak evidence.** Certifications are not in the index tables. Option A (index change): in `build_index`, append certification names as a text segment of kind `"certification"` and store `certification_tids` per candidate; bump `INDEX_FORMAT_VERSION`. Option B (simpler, no index change): read the pipe-joined `candidates["certifications"]` column in `score_pool`. With option B, inside `requirement_evidence`'s caller compute per candidate `cert_hit = any(phrase in cert.lower() for cert in certs.split("|") for phrase in req.phrases)` once per *distinct* certification string (there are few), and combine as a fourth noisy-OR term: `coverage = 1 - (1-S)(1-T)(1-G)(1-0.4*cert_hit)`. Because `cert_hit` is boolean, ten matching certifications still contribute 0.4 - bounded. Test with two factory candidates whose records differ only in `certifications`.

**3.2 - Notice-period test.**

```python
def test_notice_period_matters_only_when_stated(tmp_path, redrob_spec):
    a = candidate("CAND_0000001", signals={"notice_period_days": 15})
    b = candidate("CAND_0000002", signals={"notice_period_days": 90})
    build_index(write_jsonl([a, b], tmp_path / "n.jsonl"), tmp_path / "ix", embed=False)
    ix = DatasetIndex(tmp_path / "ix")
    t = score_pool(ix, redrob_spec, embedder=None).table.set_index("candidate_id")
    assert t.loc["CAND_0000001", "overall"] > t.loc["CAND_0000002", "overall"]
    no_notice = redrob_spec.model_copy(deep=True)
    no_notice.notice.ideal_max_days = None
    t2 = score_pool(ix, no_notice, embedder=None).table.set_index("candidate_id")
    assert abs(t2.loc["CAND_0000001", "overall"] - t2.loc["CAND_0000002", "overall"]) < 1e-6
```

(The second assertion holds because `notice_fit` returns NaN when the JD has no ideal notice, and the missing-aware mean drops it.)

**3.3 - Database field.** `CREATE TABLE IF NOT EXISTS` will **not** add a column to an existing table. Add a migration in `Database.__init__`: extend `Database._migrate`: if `schema_version` is 2, run `ALTER TABLE shortlists ADD COLUMN description TEXT NOT NULL DEFAULT ''` and set the version to 3 (bump `SCHEMA_VERSION`). Also add the column to `SCHEMA` for new databases, accept `description` in `ShortlistCreate`, insert it in `ShortlistService.create`, and display it in `ShortlistDetailPage`.

## Level 4

**4.1 - Plain-language weakness.** Candidate ideas and their trade-offs:

- *Description-informed title relevance*: raise a role's relevance when its description strongly matches the JD (e.g. `rel = max(rel_title, 0.8 × semantic_match)`). Helps plain-language candidates; but descriptions are self-written, and shuffled or embellished descriptions would gain trust. Must be measured against the adversarial set.
- *Lower the trust floor's influence on semantic evidence only*: keeps skill credibility strict while letting meaning count more.
- *Reduce lexical weight or exclude stuffed skill names from the BM25 document when credibility is low*: attacks the stuffer's advantage directly.

Measure with `scripts/run_evaluation.py` and compare `systems`, `plain_language_profiles.ranks` and `adversarial.best_stuffer_rank`. The facet-semantic experiment in `DEVELOPMENT_LOG.md` is an example of a plausible idea that was rejected by measurement.

**4.2 - Parallel index build.** Split the file into N byte ranges aligned to line starts; each worker process normalises its records and returns compact rows plus local text tables; the parent merges text tables (remapping text ids) and concatenates rows *in range order*. Determinism requirements: candidate order (`idx`) must follow file order; duplicate-id detection must be global (merge step), not per worker; text ids must be remapped consistently. Expect the parse stage to speed up roughly with cores until disk I/O dominates; embedding (the larger cost) is unchanged.

**4.3 - Top-K.** `idx = np.argpartition(-overall, K)[:K]` finds the K largest in \(O(n)\), then sort only those K: \(O(n + K \log K)\) instead of \(O(n \log n)\). Two caveats: candidates tied with the K-th score at the boundary must be included before tie-breaking, or the result depends on partition internals; and "all eligible" runs, the held-for-review list and rank numbers for every candidate still require ordering everything. At 100,000 candidates the full sort is a small fraction of the 2.85 s, so this is only worth doing at much larger scale.
