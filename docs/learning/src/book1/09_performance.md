# Performance, Scalability and Measured Quality

A ranking system that is correct but takes an hour is not useful. This part explains how TalentSignal handles 100,000 candidates on a laptop, which optimisations matter and why, what has and has not been measured, and how ranking quality is evaluated without ground truth.

All numbers in this part were measured on one machine: 16 logical CPUs, 15.7 GB RAM, Windows 11, Python 3.14, no GPU. Different hardware gives different numbers.

## The measured numbers

| Operation | Time | Peak memory | Source |
|---|---|---|---|
| Fingerprint 465 MB file (BLAKE2b) | 1.2 s | small | index `meta.json` |
| Parse + normalise 100,000 records | 16.6 s | - | `meta.json` timings |
| Build BM25 index | 1.5 s | - | `meta.json` |
| Embed 5,802 unique text segments | 107.7 s | - | `meta.json` |
| **Cold index build, total** | **137 s** | **1.99 GB** | `scripts/build_index.py` |
| **Warm scoring of 100,000 candidates** | **2.85 s** (mean of 3) | 1.94 GB process | `scripts/run_evaluation.py` |
| Competition ranking step (load, score, explain 100, validate) | 11.9 s / 12.25 s | 1.39-1.41 GB | `scripts/competition_rank.py` |
| Ranking run in the app, top 100, first use | 13 s | - | `scripts/smoke_test.py` |
| Ranking run in the app, all eligible (99,932 rows) | 5.3 s | server peak 1.66 GB | live measurement |
| Results page / filtered page / candidate detail | ~19 / 22 / 16 ms | - | smoke test (100-row run) |
| Results queries on the 99,932-row run | 150-270 ms | - | live measurement |
| Explanation of one candidate | 12.7 ms average | - | evaluation run |

One measurement is worth remembering for honesty: the competition step once took **89.9 s** while a large package installation and the web server were running at the same time. On an idle machine it took 11.9-12.3 s. Performance claims always depend on what else the machine is doing.

## Principle 1 - do expensive work once (precompute)

Figure 2.5 split the work into a one-time *index build* and a per-job *scoring*. Everything that does not depend on the job is done once and saved under `artifacts/indexes/<fingerprint>/`:

- parsing and normalising 465 MB of JSON,
- tokenising text for BM25,
- running the neural network on text (by far the most expensive step),
- integrity checks and the quality report.

Scoring then only does arithmetic on saved arrays. The *fingerprint* (a BLAKE2b hash of every byte) names the index directory, so the same file is never processed twice and a changed file is never matched to a stale index. The reference implementation hashed only the first and last megabyte; an edit in the middle would have gone unnoticed (`test_fingerprint_detects_middle_edit` proves the new behaviour).

## Principle 2 - stream, don't load

The reader processes one JSONL line at a time and immediately reduces it to compact rows (tuples of a few values per role and per skill). The parsed record is then written to `records.jsonl` and discarded. Memory therefore depends on the number of *rows kept* - not on the 465 MB raw size. JSON arrays are the exception (they cannot be streamed with a standard parser) and are capped at 512 MB with a message suggesting JSONL.

Uploads are streamed too: `DatasetService.save_upload` copies the incoming file to disk in 4 MB chunks and stops as soon as the configured limit is exceeded.

## Principle 3 - process unique text, not documents

The single most effective optimisation. In the reference data:

| Text kind | Occurrences | Unique |
|---|---|---|
| Role descriptions | 300,171 | 44 |
| Summaries | 100,000 | 3,241 |
| Headlines | 100,000 | 2,469 |
| All segments embedded | ~500,000 | 5,802 |

During indexing, `_TextTable.add()` gives each distinct text an integer id; candidates and roles store ids. Then:

- **Embeddings** are computed for 5,802 segments instead of ~500,000 - about 108 s instead of roughly two hours at the measured speed of ~65 long texts per second.
- **BM25** tokenises each unique segment once into a matrix \(T\) (segments × terms), builds a sparse *incidence* matrix \(A\) (candidates × segments, counting how often each candidate uses each segment), and gets every candidate's term counts as one sparse product \(A\,T\).
- **Phrase matching and constraint checks** run a regular expression once per unique segment and gather results per role by id. Changing the research-only check from per-role to per-unique-text cut it from 4.2 s to under 0.1 s.

On data where every text is unique, this costs the same as processing each document - so the optimisation is free when it does not help and enormous when it does.

## Principle 4 - sparse matrices

A *sparse matrix* stores only non-zero entries. The reference BM25 matrix is 100,000 candidates × 5,512 terms (unigrams and bigrams; the vocabulary is small because the text is templated - the code allows up to 150,000). Each candidate uses on average 278 terms, so only 27.8 million of the 551 million cells are non-zero (5%). Stored densely in 32-bit floats it would need 100,000 × 5,512 × 4 bytes ≈ 2.2 GB; stored sparsely (SciPy CSR format: values, column indices and row pointers) it takes 213 MB on disk. On real, diverse text the vocabulary would be far larger and the saving far greater. Scoring a query is one sparse matrix-vector product.

## Principle 5 - vectorise and avoid Python loops over rows

Every component is computed for all candidates at once with NumPy. A few patterns recur:

| Pattern | Used for | Example |
|---|---|---|
| `np.bincount(owner, weights=...)` | sum per candidate over roles | career relevance, relevant years |
| `best_per_group(group, values, n)` (one `lexsort`) | maximum per candidate and *which row* achieved it | best skill, best role evidence |
| `np.isin(codes, wanted)` on integer codes | which skill rows match a requirement | skill matching on ~1 M rows |
| `np.where`, `np.select` | piecewise formulas | band fit, notice fit |

Converting skill names to integer codes once (`DatasetIndex.skill_codes`) avoids comparing millions of strings for every requirement.

## Principle 6 - cache what repeats

| Cache | Where | What it saves |
|---|---|---|
| `IndexCache` (LRU, 3 indexes) | `services/datasets.py` | reloading Parquet tables, BM25 and embeddings |
| Pool LRU (2 scored pools) | `services/runs.py` | rescoring when opening candidate details |
| Result-table LRU (6 tables) | `services/runs.py` | re-reading Parquet for each page request |
| Query-embedding memo (≤ 5,000 texts) | `Embedder.encode_queries` | re-encoding requirement sentences and anchors (2.6 s → ~0) |
| Taxonomy `lru_cache` and title-family cache | `engine/taxonomy.py` | regex matching per title |

After a server restart the pool cache is empty. Opening a candidate then triggers a deterministic re-score from the stored JobSpec, which gives identical explanations.

## Principle 7 - never send more than a page

The browser never receives the whole result table. `GET /api/runs/{id}/results` filters, sorts and returns one page (default 50 rows, maximum 200) from the run's Parquet table in the server; the response includes `total` for the pager. The card view lazily fetches each card's explanation. **Virtual scrolling is not implemented** - it is unnecessary because no more than 200 rows are ever rendered at once.

## Where the time and memory go

| Bottleneck | Why | Mitigation in place | Possible next step |
|---|---|---|---|
| Embedding text at index time | neural network on CPU | unique segments only | batch more aggressively; quantised ONNX model; GPU at precompute only |
| Normalising records (Python per record) | per-record dict work | streaming, compact rows | multiprocessing across file chunks |
| Peak memory during build (~2 GB) | lists of role/skill tuples before conversion to DataFrames | - | write tables in chunks (Arrow record batches) |
| Explanations | Python per candidate | only on demand (≈ 13 ms each) | - |
| SQLite writes | single writer | WAL mode, throttled progress writes | - |

## Scaling to one million candidates (not benchmarked)

TalentSignal has been measured at 100,000 candidates only. The following is **reasoning, not measurement**:

- Parsing scales linearly: roughly 170 s for 1 M records at the measured rate.
- Embedding cost depends on *unique* text, which might grow from 5,802 to tens of thousands on real data with diverse descriptions - potentially hours on one CPU. This is the first wall.
- The BM25 matrix scales with total tokens (~2 GB at 10×).
- Build memory would grow roughly 10× (≈ 20 GB) with the current all-in-memory row lists - more than this machine has. Chunked table writing would be required.
- Warm scoring is linear in rows and would be around 30 s; an "all eligible" result table would hold ~1 M rows.

The honest summary: the *design* (precompute, sparse, vectorised, unique-text) extends, but the *implementation* would need chunked index building and probably approximate nearest-neighbour retrieval to pre-select candidates before full scoring. No claim of million-record support is made.

## Measuring quality without ground truth

Speed is easy to measure; quality is not. The challenge's real relevance labels were never available. TalentSignal's evaluation (`scripts/run_evaluation.py`, report in `docs/reports/EVALUATION_REPORT.md`) therefore separates what can be measured *without* labels from what needs labels.

**Label-free measurements**

| Test | Result |
|---|---|
| Keyword stuffers with every job skill at expert, 60 months **and 95/100 assessments** (synthetic, 560-candidate pool) | best rank 107; none in the top 40 |
| Deliberately impossible profiles eligible | 0 of 30 |
| Strong profiles with optional evidence removed (no assessments, GitHub, offer history) | mean score change −0.007, max drop 0.014 |
| Look-alike twins with weak engagement | all 30 rank below their originals |
| Look-alike groups (same headline, summary, title, years) with all-distinct scores | 99.4% |
| Stability: weights × random factor in [0.8, 1.2], 10 trials | 98.9% top-100 overlap, 96% top-10 overlap, Kendall τ 0.88 on the top 50 |
| Unsupported skill mentions in 200 explanations | 0 |

**Proxy-label measurements.** *Proxy labels* are hand-made stand-ins for ground truth: each of the 44 role-description templates was graded 0-5 against the reference JD, then adjusted by conditions the JD states explicitly (`engine/evaluation/proxy_labels.py`). The scorer never reads them - but it reads the same descriptions, so agreement is partly built in. They are useful for comparing variants, not for claiming accuracy.

| System (top 100) | Composite* | NDCG@10 |
|---|---|---|
| TalentSignal | 0.951 | 0.956 |
| Reference implementation (committed CSV) | **0.982** | 1.000 |
| BM25 only | 0.825 | 0.781 |
| Keyword count | 0.006 | 0.000 |

\*Composite = 0.50·NDCG@10 + 0.30·NDCG@50 + 0.15·MAP + 0.05·P@10 (the challenge's formula; Book 3 explains each metric).

The reference implementation scores higher on these proxies. Known contributors: a deliberate fairness change admits relocation-willing candidates abroad (4 in TalentSignal's top 100), behavioural signals the proxy mostly ignores (removing engagement *raises* the proxy composite to 0.967), and lower ranks for two plain-language profiles. TalentSignal does not claim to rank better than the reference; it claims bounded, explainable, configurable ranking with measured robustness.

**Ablations** - removing one part at a time (composite / overlap of top 100 with the full system):

| Removed | Composite | Overlap | Note |
|---|---|---|---|
| nothing | 0.951 | 100% | |
| requirements | 0.892 | 68% | the most important component |
| semantic | 0.885 | 88% | largest NDCG@10 drop (0.956 → 0.845) |
| career-text evidence | 0.940 | 84% | |
| integrity gate | 0.933 | 97% | 3 impossible profiles enter the top 100 |
| constraint policies | 0.943 | 98% | 6 non-relocating candidates abroad enter |
| lexical (BM25) | 0.951 | 100% | no effect on this JD |
| title trust | 0.951 | 97% | no measurable effect on this data (no ML text under unrelated titles) |
| engagement | 0.967 | 95% | proxy ignores availability; kept because the JD requires it |

!!! note "Summary of Part 9"
    Precompute once, stream, process unique text, use sparse matrices, vectorise, cache, and page results. Measured: 137 s cold build, 2.85 s warm scoring, sub-300 ms queries on 100K rows. Quality is measured with label-free robustness tests plus clearly labelled proxy metrics - on which the reference implementation is ahead.
