# TalentSignal - Complete Technical Handbook

This handbook explains *what* TalentSignal computes and *why*, from first principles to the exact formulas in
the code. File references point to the implementation so every statement can be checked.

---

## 1. Problem definition

Given a job description (JD) and a pool of candidate profiles, produce an ordered list of candidates such
that the most suitable appear first, and explain each position with evidence a recruiter can verify.

What makes this hard:

1. **The JD means more than it says.** "Production experience with embeddings-based retrieval" can be
   satisfied by someone who writes "built systems that connect users to the most relevant matches" and
   never says "embedding".
2. **Profiles are self-reported and adversarial.** Anyone can list "Pinecone, RAG, LoRA" as expert skills.
3. **Availability matters.** A perfect profile that has not logged in for six months is not hireable now.
4. **Some data is impossible or missing.** Records can be internally inconsistent; many fields are empty.
5. **Fairness and trust.** Rankings influence people's livelihoods; they must not rely on protected
   attributes or punish missing optional data, and they must be explainable.

TalentSignal treats ranking as **evidence aggregation**: for each thing the job needs, how strong and how
trustworthy is the evidence that this candidate has it?

## 2. Product architecture (summary)

Three layers (see `docs/ARCHITECTURE.md`): a pure-Python **engine** (ingestion, indexing, JD understanding,
scoring, explanation, evaluation), a **FastAPI backend** (persistence, background jobs, query API, exports),
and a **React frontend**. Two modes share the engine: **product mode** (any JD, any shortlist size, all
eligible candidates if desired) and **competition mode** (`engine/ranking/competition.py`, exactly 100 rows in
the original format).

## 3. Data architecture

### 3.1 Candidate schema
Each record (`candidate_schema.json` in the reference bundle) has:

| Section | Fields used |
|---|---|
| `profile` | headline, summary, location, country, years_of_experience, current title/company/industry |
| `career_history[]` | company, title, start/end dates, duration_months, is_current, industry, description |
| `education[]` | degree, field_of_study (shown and filterable; **not** scored), institution, tier (**never used**) |
| `skills[]` | name, proficiency (beginner…expert), endorsements, duration_months |
| `redrob_signals` | 23 platform signals (§3.2) |

### 3.2 The 23 signals and how each is used

| Signal | Use |
|---|---|
| last_active_date | engagement: activity recency (half-life 90 days) |
| recruiter_response_rate | engagement |
| avg_response_time_hours | engagement: speed = 1/(1+h/48) |
| open_to_work_flag | engagement (passive = 0.4, not 0) |
| interview_completion_rate | engagement: reliability |
| offer_acceptance_rate (-1 = none) | engagement (missing → neutral) |
| saved_by_recruiters_30d | engagement, small weight (popularity feedback loop risk) |
| skill_assessment_scores | skill evidence (verified), integrity check |
| github_activity_score (-1 = none) | evidence for the open-source requirement only; evidence completeness |
| notice_period_days | logistics |
| preferred_work_mode, willing_to_relocate | logistics; work-authorization condition |
| verified_email/phone, linkedin_connected, profile_completeness_score | evidence completeness (display, not score) |
| signup_date | data-quality check only |
| profile_views, applications, search_appearance, connections, endorsements_received, salary range | displayed / not scored (popularity or not job-relevant; salary is a negotiation matter) |

### 3.3 What the reference data looks like (measured)
100,000 records, 465 MB; all 23 signals present; 48 titles; 133 skills; **44 distinct role descriptions**
across 300,171 roles; 3,241 distinct summaries; 68.8 % non-technical titles, only 1,179 (1.2 %) direct
ML/search titles. Descriptions attached to non-technical titles are drawn from an unrelated pool. The data
is synthetic and heavily templated; the design does not depend on that but exploits it for speed.

### 3.4 Storage layout
Per dataset (`artifacts/indexes/<fingerprint>/`): normalised `records.jsonl` + `offsets.npy` (O(1) access to
any record), Parquet tables (`candidates`, `roles`, `skills`, `texts`, `integrity`), `bm25_*`,
`embeddings.npy` (float16, one row per unique text segment), `quality.json`, `meta.json`. Per run:
`artifacts/runs/<run_id>.parquet`. Metadata: SQLite.

## 4. Ingestion, validation and data quality

* **Streaming**: JSONL is read line by line (`engine/ingestion/readers.py`); the parsed record is reduced to
  compact rows immediately, so memory does not scale with raw file size.
* **Normalisation** (`validation.py`): reject only unusable records (no id, duplicate id, no profile). Repair
  everything else with a recorded warning: coerce `"0.7"`→0.7, clip out-of-range values, drop unknown enums,
  strip control characters, cap text length, order roles current-first.
* **Missing ≠ zero**: absent values and the documented `-1` sentinels become `None`. Downstream every
  sub-score treats `None` as "unknown" (§7.7).
* **Fingerprint**: BLAKE2b over every byte. The reference hashed only the first/last MB, so a mid-file
  edit could reuse a stale index; `tests/test_ingestion.py::test_fingerprint_detects_middle_edit` proves the fix.
* **Quality report**: rows read, valid, rejected (with reasons), repairs, missing-value rates per signal,
  integrity counts, duplicates, distributions.

## 5. Job description understanding

`engine/jd/parser.py` is rule-based by design (offline, deterministic, inspectable):

1. **Sectioning.** Lines are split into sections; short lines without sentence punctuation (or ending with
   ":") are headings, classified by keyword rules into *mandatory, preferred, exclusion, responsibilities,
   ideal, logistics, context*. Key-value lines ("Experience Required: 5-9 years") are not headings.
2. **Concept detection.** The taxonomy (`engine/resources/taxonomy.yaml`) defines ~25 concepts, each with
   skill names, phrases and a one-sentence semantic prototype. A concept found in a must-have section is
   mandatory (weight 1.0), in a nice-to-have section preferred (0.5), elsewhere "mentioned" (0.35). Context
   sections (e.g. the hackathon note that uses "Pinecone" as a *negative* example) are ignored.
3. **Targeted extractors**: experience ranges (`5-9 years`, `6-8 years total`, `of which 4-5`), cities
   (built-in list + the dataset's own locations), work mode, visa sponsorship, notice ("sub-30-day",
   "buy out up to 30 days").
4. **Declared conditions** (constraints) via patterns: consulting-only careers, pure research, non-coding
   leads, title-chasing, CV/speech without NLP/IR, LLM-wrapper-only, closed-source-only, work authorization.
5. **Role families** from the title ("Senior AI Engineer" → ML engineering) plus search/ranking when those
   concepts are mandatory.

Every requirement and condition carries `source_text` - the sentence it came from - shown in the review UI.
The output (`JobSpec`, `engine/jd/spec.py`) is editable: importance, weights, hard gates, skills, phrases,
semantic text, locations, notice, policies, component weights.

## 6. NLP foundations used

### 6.1 Tokenisation and the vector space model
Text is lower-cased and split into tokens (`[a-z0-9][a-z0-9+#]*` with internal `-`/`.` allowed, so "c++",
"node.js" and "learning-to-rank" survive). Unigrams and bigrams are used so "vector search" is one feature.
A document becomes a sparse vector of term counts.

### 6.2 TF-IDF (background; not used in scoring)
`tfidf(t,d) = tf(t,d) · log(N / df(t))`: frequent-in-document, rare-in-corpus terms weigh more. The
reference used TF-IDF cosine against the whole JD. TalentSignal replaces it with BM25 (better length
normalisation and saturation) plus embeddings.

### 6.3 BM25 (`engine/retrieval/bm25.py`)
```
BM25(q, d) = Σ_{t∈q}  idf(t) · tf(t,d)·(k1+1) / ( tf(t,d) + k1·(1 − b + b·|d|/avgdl) )
idf(t)     = ln(1 + (N − df(t) + 0.5)/(df(t) + 0.5))          k1 = 1.2, b = 0.75
```
*Saturation* (k1): the 10th mention of "ranking" adds little. *Length normalisation* (b): long profiles are
not rewarded for verbosity. The query-independent part is precomputed into a sparse matrix W, so scoring
100K candidates is one sparse matrix-vector product. Documents are assembled as
`tf = A · T` where T is term counts of *unique segments* and A is a candidate×segment incidence matrix.

The query is the union of requirement skills and phrases (weights = requirement weights) plus the title.
BM25 has no absolute scale, so the component is the **percentile among candidates with a positive score**
(ties share the same percentile; 0 for no match).

### 6.4 Embeddings and cosine similarity
A sentence encoder maps text to a vector such that semantically similar texts are close. TalentSignal uses
**BAAI/bge-small-en-v1.5** (33M parameters, 384 dimensions, MIT licence) on CPU. Vectors are L2-normalised,
so cosine similarity is a dot product: `cos(u,v) = u·v / (|u||v|) = u·v`.

Why this model: small enough to embed the reference pool on CPU in under two minutes, strong retrieval
quality for its size, permissive licence, runs fully offline from a local directory.

**Calibration.** Raw cosines are not probabilities and unrelated English text scores ~0.4-0.55. Measured on
the reference index (`scripts/calibrate_semantic.py`): unrelated descriptions 0.41-0.55, explicit matches
0.75-0.85. Short requirement prototypes therefore use `s = clip((c − 0.62)/(0.80 − 0.62), 0, 1)`.
Long free-form query text (the JD focus) has a different scale, so it gets a **per-query window**: its median
similarity to 12 fixed unrelated "anchor" sentences plus 0.08 is the floor, floor + 0.18 the ceiling.

**Unique-segment trick.** Only distinct headlines, summaries, titles and descriptions are embedded (5,802
for 100K candidates) and gathered back per candidate by id.

### 6.5 Hybrid retrieval
Lexical (BM25, exact terms), dense (embeddings, meaning) and structured evidence (skills, assessments,
titles) fail differently: BM25 misses paraphrases, embeddings blur specifics ("FAISS" vs "Milvus") and are
fooled by stylistic similarity, structured fields can be stuffed. Combining them, and weighting text by how
trustworthy its source is, is more robust than any one alone. The ablations (§11.4) measure each part.

## 7. Feature engineering and scoring mathematics

All features are computed for the whole pool with NumPy (`engine/features/*`, orchestrated by
`engine/ranking/scorer.py`). Every component lies in [0, 1].

### 7.1 Title relevance
Titles map to role families by ordered regex rules (taxonomy). The JD has target families with weights.
```
relevance(title) = max_f  w_f · affinity(f, family(title))
```
`affinity` is a hand-set symmetric table (same family 1.0, ML↔search 0.9, backend↔ML 0.35, any↔non-technical
0). **Role fit** = 0.65 · relevance(current title) + 0.35 · career relevance, where career relevance is the
months×recency-weighted mean relevance of all roles (recency = exp(−months_since_end/48)).

### 7.2 Skill evidence (per requirement)
For each skill row matching a requirement:
```
usage  u = 1 − exp(−months_used/18)                (missing months → 0.6)
claim  c = proficiency · (0.35 + 0.65·u)           (beginner .25, intermediate .5, advanced .75, expert 1)
e      = 0.5·c + 0.5·assessment/100  if a platform assessment exists, else c
S      = max over matching skills of e  ×  credibility
credibility = 0.5 + 0.5 · max_role_relevance
```
*Why max, not sum:* the reference summed skill weights, so listing more keywords always increased the score.
With max, ten synonyms count once (`test_adding_synonym_skills_does_not_inflate`).
*Why credibility:* skill claims unsupported by any related role count at half weight.
*Why blend assessments:* verified scores can raise or lower the claim; their absence is neutral (no discount).

### 7.3 Text evidence (per requirement)
For each unique text segment: phrase hit h ∈ {0,1} and calibrated semantic similarity s to the
requirement's prototype.
```
match(text) = 1 − (1 − 0.75·h)·(1 − s)
role evidence = match(description) · trust · (0.5 + 0.5·recency)
trust = 0.3 + 0.7 · relevance(role title)
self evidence = 0.6 · max(match(summary), match(headline)) · credibility
T = max(best role evidence, self evidence)
```
*Trust* encodes "a description is credible to the extent its job title is consistent with it". It also
neutralises the reference data's shuffled descriptions without any dataset-specific rule.

### 7.4 Coverage (noisy-OR)
```
coverage = 1 − (1 − S)(1 − T)(1 − G)       G = optional signal evidence (e.g. 0.8·GitHub/100)
```
Noisy-OR stays in [0,1], rewards independent corroboration and never lets one source subtract from another.
Requirements component = weighted mean of coverage (weights from the spec). Mandatory coverage is also kept
for tie-breaks and the "must-haves met" count (met ≥ 0.65, partial ≥ 0.30).

### 7.5 Semantic component (holistic)
Best calibrated similarity between the JD focus text (title + responsibilities + must-have prototypes) and
any role description, × trust × recency weight. Summaries are excluded here because every summary scored
0.70-0.81 against the focus text (no discrimination, measured).

### 7.6 Experience component
`0.45·band + 0.35·relevant + 0.20·seniority` where band is a trapezoid (1 inside the ideal band, ramps to
0.75 at the soft limits, exponential decay outside; overqualification decays slower than underqualification),
relevant = min(1, relevant_years/target) with relevant_years = Σ relevance·months/12, and seniority compares
title levels (junior 1 … principal 5; untitled levels inferred from years).

### 7.7 Engagement and logistics (missing-aware means)
```
combined = Σ_k w_k·x_k·avail_k / Σ_k w_k·avail_k        (0.5 if nothing is available)
```
Engagement weights: recency .25, response rate .25, speed .10, open-to-work .15, interview attendance .15,
offer acceptance .05, saved by recruiters .05. Logistics: location .5 (preferred city 1, acceptable 0.9,
same country 0.75/0.6 depending on relocation, abroad 0.1-0.5 depending on visa policy), notice .35 (1 up to
the ideal, linear to 0.7 at the acceptable limit, decaying to a 0.2 floor), work mode .15.
Activity is measured against an **as-of date** = the latest activity date in the dataset (configurable), so
results do not drift with the wall clock - the reference hard-coded a date.

### 7.8 Overall score
```
base    = Σ_c w_c · component_c        (weights normalised; disabled components re-normalised away)
overall = base × Π factor_i            (declared conditions with policy "penalize")
```
Default weights: requirements .34, role fit .20, semantic .12, lexical .05, experience .10, engagement .11,
logistics .08. The score is a weighted evidence summary, **not** a calibrated probability.

### 7.9 Normalisation choices
Components are built on absolute scales (coverage, calibrated similarity, fractions) wherever possible, so
a score means the same in a 50-candidate upload and a 100K pool. The exception is BM25 (percentile), which
has no natural scale. Min-max normalisation over the pool (used by the reference) was avoided because one
outlier changes everyone's score.

### 7.10 Eligibility, gates and ordering
A candidate is held out of the shortlist (still inspectable, with reasons) when: a condition has policy
"exclude"; a requirement marked *hard* has coverage < its minimum; the experience minimum is marked hard; or
a critical integrity finding exists and the integrity policy is "exclude". Order: eligible first, overall
desc, mandatory coverage desc, engagement desc, candidate_id asc - fully deterministic.

## 8. Integrity detection (`engine/integrity/checks.py`)

| Check | Severity | Measured on reference data |
|---|---|---|
| ≥2 skills "expert" with 0 months used | critical (1 skill: warning) | 21 candidates |
| Stated years vs Σ role months differ > 3 years | critical (1.5-3: warning) | 47 |
| Assessment for a skill not listed | warning | 36 |
| Role duration contradicts its dates; end before start; future start | warning | 0 |
| Overlapping roles > 6 months | info | 0 |
| Salary min > max; activity before sign-up; title mismatch | info (data quality) | 18,865 / 7,496 / 0 |
| Identical content under different ids | warning | 0 |
| ≥4 JD skills claimed (≥0.5 strength) with no related role (JD-dependent) | warning | 431 for the Redrob JD |

Critical = internally impossible as written → held for human review by default (policy switchable to
"flag"). Never labelled fraud: the record may simply be wrong. The 68 critical candidates match the
reference's count and the brief's "~80 honeypots". The "company younger than the tenure" honeypot
mentioned in the spec cannot be checked: the data contains no founding dates.

## 9. Explainable AI

Explanations are produced from the **same arrays the score came from**: for each requirement the scorer keeps
the index of the best skill row and best role row. `engine/explanations/explain.py` turns those into evidence
items (skill + proficiency + months + assessment; role title/company + matched phrases; summary phrases;
GitHub value), then:

* `validator.validate_evidence` re-checks each item against the raw record (skill exists with that
  proficiency; assessment value matches; quoted phrases literally occur in that role's description).
* `validator.validate_text` scans the generated claims sentence for any known skill/technology name and
  confirms it appears in the record; on failure a minimal factual sentence is used instead.
* Concerns are rule-generated from facts (notice, response rate, inactivity, experience, location,
  interviews, triggered conditions, integrity findings); missing information is listed separately and
  explicitly not held against the candidate.
* **Differentiators**: component-wise difference between the candidate and the mean of the ±3 neighbouring
  ranks, weighted by component weight - answers "why above/below similar candidates".
* Tone depends on rank and score ("Top match", "Strong", "Good", "Partial", "Weak", "Held for review").

Measured: 0 unsupported skill mentions in 200 audited explanations; 100 distinct summaries in the top 100.

## 10. Evaluation metrics (`engine/evaluation/metrics.py`)

* **DCG@k** = Σ_{i≤k} (2^{rel_i} − 1)/log2(i+1); **NDCG@k** = DCG@k / IDCG@k, with IDCG from the whole
  labelled pool, so missing strong candidates is penalised.
* **P@k** = fraction of the top k with rel ≥ 3.
* **AP@100** = (1/min(R,100)) Σ_{i≤100, rel_i≥3} P@i, R = relevant items in the pool.
* **Competition composite** = 0.50·NDCG@10 + 0.30·NDCG@50 + 0.15·MAP + 0.05·P@10.
* Stability: top-k overlap and Kendall τ = (concordant − discordant)/(n(n−1)/2).
The spec did not define gain or MAP cut-off; the choices above are documented assumptions.

## 11. Evaluation results (all relevance numbers use PROXY labels)

### 11.1 Why proxies
The hidden ground truth was never available. Proxy labels (`engine/evaluation/proxy_labels.py`) =
hand-assigned grades of the 44 description templates (rubric in the YAML) adjusted by JD-stated conditions.
The scorer never reads them but reads the same descriptions, so agreement is partly built in. They are good
for comparing variants and catching regressions, not for claiming real-world accuracy.

### 11.2 Systems (top-100)
| System | Composite | NDCG@10 | NDCG@50 | Critical in top-100 |
|---|---|---|---|---|
| TalentSignal | 0.951 | 0.956 | 0.910 | 0 |
| Reference implementation (committed CSV) | **0.982** | 1.000 | 0.941 | 0 |
| BM25 only | 0.825 | 0.781 | 0.895 | 7 |
| Keyword count | 0.006 | 0.000 | 0.019 | 0 |

The reference scores higher on these proxies. Known contributors: TalentSignal deliberately admits
relocation-willing candidates abroad (4 in its top 100; fairness decision, §12), weighs behavioural signals
the proxy mostly ignores (removing engagement *raises* the proxy composite to 0.967), and places two
plain-language profiles at ranks ~81 and ~97. 73 % of the two top-100 lists overlap.

### 11.3 Robustness
* Keyword stuffers with every JD skill at expert, 60 months, and 95/100 assessments: best rank 107 in a
  560-candidate adversarial pool (40 strong real profiles); none in the top 40.
* Impossible profiles: 0 eligible. Removing optional evidence from strong profiles: mean score change
  −0.007 (max drop 0.014). Look-alike twins with weak engagement: all 30 rank below their originals.
* Look-alike groups (same headline, summary, title, years): 99.4 % have all-distinct scores.
* Weight perturbation ±20 % (10 trials): top-100 overlap 98.9 %, top-10 overlap 96 %, Kendall τ (top 50) 0.88.

### 11.4 Ablations (composite / overlap with full top-100)
Requirements −0.059 / 68 %; semantic −0.066 / 88 %; career text −0.012 / 84 %; logistics −0.010; integrity
gate −0.018 and 3 critical profiles enter the top 100; constraints −0.008 and 6 non-relocating candidates
abroad enter; lexical 0.000 / 100 % (no effect on this JD); title trust 0.000 / 97 % (the data has no
ML-sounding descriptions under unrelated titles, so the safeguard is untested by it).

## 12. Fairness and limitations

* No protected attribute is used or inferred: names, gender, age, nationality are not features; education
  *tier* (prestige) is never used; field of study is filterable but not scored.
* Location is used only as the JD states it. The work-authorization condition fires only for candidates
  outside the hiring country who explicitly will not relocate - inferring visa needs would require inferring
  citizenship.
* Missing optional data is neutral by construction (§7.7) and measured (§11.3).
* Popularity signals (profile views, search appearances) are not scored; "saved by recruiters" has a 5 %
  share of engagement only, because popularity-based ranking creates feedback loops.
* Limitations: rule-based JD parsing covers the taxonomy's domains best; the affinity table and calibration
  constants are hand-set (documented, editable); proxy-based evaluation; sessions are not authentication;
  scalability beyond 100K is not benchmarked.

## 13. Performance engineering

| Technique | Effect (measured) |
|---|---|
| Streaming parse to compact rows | 100K records parsed in 17 s |
| Unique-segment embedding | 5,802 encodes instead of ~400K; 108 s |
| Sparse BM25 with precomputed saturation | query = one sparse mat-vec |
| Regex per unique text (not per role) | research-only check 4.2 s → <0.1 s |
| Integer skill codes | ~1M-row skill matching without string compares |
| Memoised query embeddings | prototype encoding 2.6 s → ~0 on repeat runs |
| Result tables in Parquet + LRU | page/filter on 99,932 rows: 150-270 ms |
Warm scoring: 2.85 s for 100K. Cold index: 137 s, 1.99 GB peak. Competition ranking step: 11.9 s,
1.39 GB peak (idle machine).

## 14. Design decisions and trade-offs

| Choice | Alternative | Why this one |
|---|---|---|
| Weighted evidence model | Learning-to-rank (LightGBM) | No labels; a learned model on proxy labels would learn the proxy. The feature set is LTR-ready when real feedback exists |
| Rule-based JD parser | LLM extraction | Offline, deterministic, inspectable, free; recruiter review covers its gaps |
| bge-small on unique segments | Larger models / cross-encoder re-ranking | CPU budget; cross-encoders on 100K are too slow; a re-ranker over the top few hundred is a natural next step |
| Absolute calibrated scales | Pool min-max | Scores stay comparable across pools |
| Policies visible to recruiter | Hidden multipliers | Accountability; the recruiter owns trade-offs |
| SQLite | Postgres | Zero-ops for a single-node tool; schema portable |
