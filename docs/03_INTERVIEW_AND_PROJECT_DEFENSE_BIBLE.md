# TalentSignal - Interview and Project Defense Bible

Answers are written to be said out loud, then backed by numbers you can show. Every figure here comes from
`docs/reports/EVALUATION_REPORT.md`, the smoke test, or the benchmark scripts - do not quote numbers that are
not in those files.

---

## 1. Elevator pitch (30 seconds)

"TalentSignal ranks a pool of candidates against a job description and explains every position. It reads the
JD into an editable list of must-haves and nice-to-haves, then scores each candidate on how strongly their
skills, platform assessments and actual work history evidence each requirement - trusting work descriptions
only as far as the job title supports them - plus experience, availability and logistics. Every claim in an
explanation is checked against the candidate's record. On 100,000 candidates it scores the pool in about
three seconds on a laptop CPU, with no external AI APIs."

## 2. Problem statement
Recruiters face large pools where keyword search fails both ways: it rewards people who stuff keywords and
misses people who describe the right work in plain language. They also need to know *why* a candidate is
recommended and whether they are actually available. The goal is decision support: a ranked, explained,
filterable shortlist - not an automatic hire/no-hire.

## 3. Architecture questions

**Why three layers (engine, API, UI)?** The engine is a library so it can be tested without HTTP and reused by
the CLI, competition mode, the evaluation harness and the API. The API adds persistence, jobs and access
control; the UI is replaceable.

**Why precompute an index?** Parsing 465 MB and embedding text is the expensive part (137 s cold). Done once per
file (keyed by a full-file hash), ranking becomes cheap array arithmetic (2.85 s warm).

**Why embed unique text segments?** The reference pool has 44 distinct role descriptions across 300K roles and
3,241 distinct summaries. Embedding 5,802 unique segments instead of 100K documents made dense semantics
affordable on CPU. On a dataset with no duplication it costs the same as embedding everything.

**Why background jobs with threads?** Index builds and scoring take seconds to minutes; the UI polls progress
and can cancel. The heavy work is NumPy/PyTorch, which releases the GIL, and threads share the in-memory index.

**Why SQLite and Parquet?** Single-node tool, zero operations. Run results are columnar, so filtering and
sorting 100K rows takes 150-270 ms.

## 4. Technology stack questions
* **FastAPI + Pydantic**: request validation and the JobSpec model are the same Pydantic classes, so the
  editable spec is validated end to end.
* **React + TypeScript + Vite, no UI framework**: a small, explicit design system; types mirror the API.
* **bge-small-en-v1.5**: MIT licence, 384-d, CPU-friendly, strong for its size, runs offline.
* **No LLM in the core**: offline, deterministic, free, and cannot hallucinate qualifications into
  explanations. An LLM could later assist JD extraction - the recruiter review step already exists.

## 5. Ranking algorithm - the 2-minute explanation
1. Parse the JD into requirements, each a group of skills + phrases + a one-sentence meaning.
2. For each requirement and candidate: **skill evidence** = the best single matching skill
   (proficiency × usage, blended 50/50 with a platform assessment when one exists) × credibility;
   **text evidence** = the best role description match (phrase hit and/or calibrated embedding similarity) ×
   title trust × recency; combine with **noisy-OR**: 1 − (1 − S)(1 − T)(1 − G).
3. Components: requirement coverage, role fit, semantic, BM25, experience, engagement, logistics →
   weighted sum (weights editable).
4. JD-declared conditions apply as visible policies (ignore / penalise × factor / exclude).
5. Hard gates and critical integrity findings hold candidates for review instead of changing their score.
6. Deterministic order; explanations built from the exact evidence rows used.

## 6. Mathematical questions (with answers)

**Q: Why max over skills instead of sum?** A sum grows with the number of keywords listed, which is exactly
what keyword stuffers exploit. The max is bounded: ten synonyms count once. Test:
`test_adding_synonym_skills_does_not_inflate`.

**Q: Why noisy-OR?** If sources were independent detectors with hit probabilities S and T, the probability at
least one fires is 1 − (1 − S)(1 − T). It stays in [0, 1], increases with corroboration, and a weak source
never lowers a strong one - unlike averaging.

**Q: What is BM25 and why not TF-IDF?** BM25 adds term-frequency saturation (k1 = 1.2) and document-length
normalisation (b = 0.75) to IDF weighting. Long profiles are not rewarded for verbosity and repeating a word
has diminishing returns. Formula in Handbook §6.3.

**Q: Why convert BM25 to a percentile?** BM25 has no absolute scale - values depend on the query and corpus.
A percentile among matching candidates is bounded and interpretable. I measured that this component did not
change the top 100 for the Redrob JD, and I say so in the report.

**Q: How did you calibrate cosine similarity?** Measured distributions: unrelated descriptions 0.41-0.55,
explicit matches 0.75-0.85, so short prototypes map linearly from 0.62 → 0 to 0.80 → 1. Long JD text has a
different scale, so its window is set per query from its median similarity to 12 fixed unrelated anchor
sentences (+0.08, width 0.18).

**Q: How do you handle missing values in averages?** Weighted mean over *available* sub-signals only:
Σ w·x·avail / Σ w·avail. Measured: stripping assessments, GitHub and offer history from 30 strong profiles
changed scores by −0.007 on average (max 0.014).

**Q: Is the score a probability?** No. It is a weighted summary of evidence on a 0-1 scale. Calibrating to a
probability of a hiring outcome would need outcome labels we do not have.

**Q: NDCG?** DCG = Σ (2^rel − 1)/log2(i + 1); normalised by the ideal ordering of the whole labelled pool, so
missing strong candidates costs score. Composite = 0.5 NDCG@10 + 0.3 NDCG@50 + 0.15 MAP + 0.05 P@10.

**Q: Kendall tau?** (concordant − discordant)/(n(n−1)/2) over pairs present in both rankings; I use it for
stability under weight perturbation (0.88 on the top 50).

## 7. NLP / ML questions

**Q: Why not fine-tune a model or train learning-to-rank?** There are no relevance labels. Training on my own
proxy labels would just teach the model my heuristics. The features are LTR-ready: with recruiter feedback
(shortlist / reject / hire) a LightGBM LambdaMART model is the next step.

**Q: Why not a cross-encoder re-ranker?** Too slow for 100K on CPU; a re-ranker over the top few hundred would
be a sensible addition, evaluated with the same harness.

**Q: How does it catch "plain-language" candidates?** Through semantic similarity of their role descriptions to
requirement prototypes and the JD focus, gated by title trust. Honest result: of 6 such profiles, ranks were
8, 12, 22, 51, 81, 97 - all in the top 100, but two lower than I would like. I tried facet-level semantic
matching to improve this; it lowered the proxy composite (0.951 → 0.883 at full weight) and barely moved
those ranks, so I removed it.

**Q: What does title trust do?** Text evidence from a role is multiplied by 0.3 + 0.7 × relevance of that
role's title. It encodes "a description is credible as far as the job title supports it". In the reference
data it neutralises descriptions shuffled under unrelated titles. The ablation shows no change on this dataset
because no ML-sounding descriptions appear under unrelated titles - it is a safeguard, not a measured gain.

## 8. Backend questions
* **Upload safety**: streamed in 4 MB chunks to a server-generated filename, size limit enforced while
  streaming, extension allow-list, empty files rejected; user filenames are only display text.
* **Path imports**: resolved with `resolve(strict=True)` and allowed only inside configured directories.
* **Errors**: one JSON shape everywhere; unexpected exceptions are logged with a stack trace and returned as a
  generic 500 (no internals leaked).
* **Job recovery**: jobs running during a crash are marked failed at start-up; index builds write to a
  `.building` directory then rename, so a half-built index is never used.

## 9. Frontend questions
* **100K results?** Never rendered at once: server-side filter/sort/paging (≤ 200 rows per page); cards lazily
  fetch explanations.
* **XSS?** React escapes text; no `dangerouslySetInnerHTML`; CSP `default-src 'self'` plus nosniff and
  frame-deny headers.
* **State**: small hooks (`useAsync`, `usePoll`, `useDebounced`); no global store needed.

## 10. Database questions
Six tables (datasets, jobs, runs, shortlists, shortlist_items, activity) with cascading foreign keys and WAL.
Run results are not in SQLite on purpose: Parquet files are columnar and compress well for 100K-row tables.

## 11. Performance questions (measured)
Cold index 137 s / 1.99 GB peak; warm scoring 2.85 s; 100-row run cold 13 s including the first model and index
load; all-eligible run 5.3 s with 99,932 rows; results pages 150-270 ms on that run; competition step 11.9 s /
1.39 GB on an idle machine (89.9 s once under heavy concurrent load). Biggest wins: regex per unique text
(4.2 s → <0.1 s), memoised query embeddings (2.6 s → ~0), integer skill codes.
**Million-record scale has not been benchmarked**; I would not claim it.

## 12. Security questions
Session ids separate history between browsers but are not authentication - the README says to put real auth in
front before exposing it. Other measures: CSV/XLSX formula-injection neutralisation, upload limits, safe paths,
.docx zip-bomb guard, control-character stripping, no secrets in code, network blocked in competition ranking.

## 13. Fairness questions
* No names, gender, age or nationality as features; education prestige (tier) is never used.
* Missing optional data is neutral (measured).
* The work-authorization condition only fires for candidates abroad who explicitly will not relocate:
  penalising everyone abroad would implicitly assume they need a visa, i.e. infer citizenship.
* Integrity findings hold candidates for human review with evidence; nothing is labelled fraud.
* Popularity signals are mostly excluded to avoid rich-get-richer loops.
* Every policy is visible and editable by the recruiter.

## 14. Evaluation questions
**Q: How do you know it works without ground truth?** I separate what I can measure from what I cannot.
Measurable without labels: adversarial behaviour (stuffers with perfect assessments best rank 107 of 560;
impossible profiles never eligible), look-alike separation (99.4 % of groups distinct), stability (98.9 %
top-100 overlap under ±20 % weight noise), explanation grounding (0 unsupported mentions in 200), latency and
memory. For relevance I built clearly labelled proxy labels and use them only comparatively.

**Q: Is it better than the reference implementation?** On my proxy labels, no: 0.951 against 0.982. Known
reasons: a deliberate fairness change admits relocation-willing candidates abroad, behavioural signals the
proxy ignores, and two plain-language profiles ranked lower. TalentSignal adds what the reference lacks -
configurable JDs, bounded evidence, grounded explanations, a full product, tests - but I do not claim a
ranking-quality win I have not measured.

## 15. Trade-offs and alternatives
| Decision | Alternative | Trade-off accepted |
|---|---|---|
| Rule-based JD parsing | LLM extraction | Less coverage of unusual JDs; recruiter review compensates |
| Hand-set weights and affinities | Learned weights | Transparent but unoptimised; LTR when labels exist |
| bge-small | bge-base / e5-large | Faster, slightly weaker semantics |
| Threads + SQLite | Celery + Postgres | Simple single-node deployment; not horizontally scalable as is |
| Session ids | Auth | Easy local use; not safe for public hosting |

## 16. Difficult questions

**"Your semantic thresholds look arbitrary."** They are measured and documented with the data that produced them
(Handbook §6.4), and a script reproduces the distributions for any model.

**"Isn't title trust just overfitting to the dataset's shuffled descriptions?"** The principle is general
(credibility depends on consistency) and the ablation shows it has no effect on this data's top 100. It costs
nothing when titles and descriptions agree and protects when they do not.

**"Your proxy labels use descriptions; so does your model. Isn't evaluation circular?"** Partly, and the report
says so. That is why the strongest evidence is from label-free tests (adversarial, look-alike, stability,
grounding), and why I did not tune weights to the proxy.

**"A candidate has no GitHub - do you penalise them?"** Not in the score. Missing GitHub only means the optional
open-source requirement is not demonstrated, and it is listed under "missing information", explicitly not held
against them.

**"What happens with a JD for a nurse?"** The parser finds few known concepts and says so in extraction notes;
title relevance falls back to word overlap with the JD title; the recruiter adds custom requirements (skills +
phrases + a semantic sentence). It works, but quality depends on the taxonomy - that is a stated limitation.

## 17. Scenario questions
* *The recruiter thinks notice period matters more.* Raise the logistics weight or set the notice ideal; the
  run is re-run with the edited spec (history keeps both).
* *A top candidate looks suspicious.* Open the profile: integrity findings with evidence, verified vs
  self-reported markers per skill, differentiators vs neighbours.
* *Upload of a 2 GB CSV.* Streamed to disk with a limit; better: import by path from an allowed directory.
* *Two candidates with identical text.* Engagement and assessments separate them; tests show twins with weak
  engagement always rank below the original.

## 18. Demonstration script (8 minutes)
1. **Dashboard** - shared 100K dataset, health, recent runs (30 s).
2. **Dataset detail** - quality report: 68 critical integrity findings, missing-value rates, "missing is neutral" (1 min).
3. **New ranking** - load the Redrob JD preset, Analyse: show must-haves with source sentences, the hackathon
   note ignored, declared conditions with policies; change shortlist size to Top 50 (1.5 min).
4. **Results** - progress bar, score distribution, requirements met; filter India + 5+ years + FAISS; card view
   with grounded summaries; "Held for review" tab (1.5 min).
5. **Candidate profile** - score composition table, requirement evidence with verified badges, concerns vs
   missing information, career timeline (1.5 min).
6. **Compare** three candidates; save two to a shortlist with a note; export XLSX and the competition CSV (1 min).
7. **Close** with the evaluation report: what is measured, what is proxy, where the reference wins (1 min).

## 19. Concepts to study before an interview
BM25 and IDF; vector space model; sentence embeddings, bi-encoders vs cross-encoders; cosine similarity and
normalisation; hybrid retrieval; noisy-OR; NDCG, MAP, precision@k, Kendall tau; ablation studies;
calibration vs ranking; learning-to-rank (pointwise/pairwise/listwise, LambdaMART); sparse matrices (CSR);
vectorisation in NumPy; FastAPI dependency injection; SQLite WAL; REST pagination; React effects and stale
requests; CSP and formula injection; algorithmic fairness (proxies for protected attributes, feedback loops).
