# Important Code Explained

This part explains the pieces of code that matter most for understanding and defending TalentSignal. For each piece you get: the problem it solves, what the important statements do, why this approach, what happens if it is removed or changed, alternatives, and complexity. *n* is the number of candidates, *r* the number of role rows (about 3*n*), *k* the number of skill rows (about 10*n*), *u* the number of unique text segments.

## 1. `best_per_group` - "the best row for each candidate"

#@include engine/features/evidence.py::best_per_group

**Problem.** Many questions have the form "for each candidate, which of their rows has the highest value, and which row is it?" - the best matching skill, the best role description. A Python loop over a million rows would take seconds per requirement.

**How it works.**

1. `np.lexsort((-values, group))` sorts all rows by `group` (the candidate index) and, within a candidate, by value descending (hence `-values`). `lexsort` sorts by the *last* key first.
2. `g = group[order]` lists candidate indices in that order; `first[1:] = g[1:] != g[:-1]` marks the first row of each candidate - which is that candidate's maximum.
3. `sel` are the original positions of those first rows. Their values go into `best`, their positions into `arg`.

Candidates with no rows keep `best = 0` and `arg = -1`.

**Why.** One vectorised sort replaces a loop; it also returns the *argmax*, which explanations need. **If removed** - e.g. replaced by `np.maximum.at` - you would get the maxima but lose which row won, and explanations could no longer point at the exact skill or role. **Alternatives:** `pandas.groupby().idxmax()` (similar complexity, more overhead); a sort-free `np.maximum.at` plus a second pass to find the argmax. **Complexity:** \(O(m \log m)\) time for \(m\) rows, \(O(m + n)\) memory.

## 2. `skill_row_strength` - bounded, assessment-aware skill claims

#@include engine/features/evidence.py::skill_row_strength

**Problem.** Turn (proficiency, months used, optional assessment) into one strength in [0, 1] that cannot be inflated by claiming "expert" without usage.

**Statements.** Missing proficiency becomes 0.5 and missing months a usage of 0.6 (neutral middles). `claim = lv * (0.35 + 0.65 * usage)` caps a zero-usage claim at 35% of its level. `np.where(np.isnan(assessed), claim, 0.5*claim + 0.5*assessed/100)` blends in an assessment only where one exists.

**If changed.** Remove the usage factor and "expert, 0 months" becomes a full-strength claim - exactly the honeypot pattern. Weight assessments 100% and a candidate with a low assessment but long real usage collapses; weight them 0% and verified evidence is wasted. **Complexity:** \(O(k)\), computed once per scoring run for all skill rows.

## 3. `TextMatcher` - phrases and meaning over unique texts

#@include engine/features/evidence.py::TextMatcher

**Problem.** For each requirement, score every candidate text by exact phrase and by meaning - without processing 300,000 role descriptions.

**Statements.** The constructor lower-cases only the evidence kinds (descriptions, summaries, headlines) once. `phrase_hits` builds *one* alternation regex per requirement, longest terms first, wrapped in `(?<![a-z0-9]) … (?![a-z0-9])` so terms match as whole words, then scans each unique text once. `semantic` is a single matrix-vector product `self.emb @ vector` over all unique texts, then calibration and masking. `match` combines them by noisy-OR.

**Why.** Work is proportional to *u* (5,802 on the reference data), not to *r*. **If the word boundaries were removed**, "rag" would match "storage" and "java" would match "javascript". **Complexity:** phrase matching \(O(u \cdot L)\) where \(L\) is text length; semantics \(O(u \cdot d)\) with \(d = 384\).

## 4. The heart of `score_pool`: combination, policies and ordering

The following passage (from `engine/ranking/scorer.py`) turns component arrays into the overall score:

```python
# excerpt from score_pool (engine/ranking/scorer.py)
weights = spec.weights.normalized()
disabled = set(opt.disabled_components)
if not semantic_ok:
    disabled.add("semantic")
active = {k: v for k, v in weights.items() if k not in disabled}
total_w = sum(active.values())
if total_w <= 0:
    raise ValueError("All score components are disabled.")
active = {k: v / total_w for k, v in active.items()}
base = np.zeros(n, dtype=np.float64)
for k, wk in active.items():
    base += wk * np.asarray(components[k], dtype=np.float64)
```

**Statements.** Normalise the recruiter's weights; drop disabled or unavailable components and *re-normalise* so the remaining weights still sum to 1; accumulate the weighted sum for all candidates at once.

**If the re-normalisation were removed**, disabling the semantic component (12%) would silently cap every score at 0.88 and make runs with and without the model incomparable.

Later in the same function, each declared condition is detected and applied according to its policy:

```python
# excerpt from score_pool (engine/ranking/scorer.py)
for c in spec.constraints:
    det = detectors.get(c.id)
    if det is None:
        continue
    hit = np.asarray(det(), dtype=bool)
    tbl[f"c_{c.id}"] = hit
    if not opt.use_constraints or c.policy == "ignore":
        continue
    if c.policy == "penalize":
        factor = np.where(hit, factor * c.factor, factor)
    elif c.policy == "exclude":
        eligible &= ~hit
        for i in np.flatnonzero(hit):
            reasons[i].append(c.label)
overall = np.clip(base * factor, 0, 1)
```

`detectors` is a dictionary of small lambdas keyed by condition id; a condition with no detector is skipped rather than guessed. The triggered flags are stored as `c_<id>` columns even when the policy is "ignore", so the UI can still show them as concerns.

Finally the deterministic ordering:

```python
# excerpt from score_pool (engine/ranking/scorer.py)
tbl = tbl.sort_values(
    ["eligible", "overall", "mandatory_coverage", "engagement", "candidate_id"],
    ascending=[False, False, False, False, True], kind="mergesort").reset_index(drop=True)
tbl["rank"] = np.where(tbl["eligible"], np.arange(1, n + 1), 0).astype(np.int32)
```

`kind="mergesort"` is a *stable* sort. Ranks are assigned only to eligible rows (which come first), held rows get 0. **Complexity of `score_pool`:** dominated by \(O((r + k)\log(r + k))\) for the per-requirement `best_per_group` sorts, times the number of requirements; measured 2.85 s for 100,000 candidates and 23 requirement/auxiliary concepts.

## 5. `_percentile_positive` - a tie-aware percentile

#@include engine/ranking/scorer.py::_percentile_positive

**Problem.** BM25 values have no fixed scale; turn them into [0, 1] so they can be weighted. **Statements.** Only positive scores participate; values are rounded to 6 decimals (so floating-point noise does not split ties); `rankdata(method="max")` gives tied values the same, highest rank. **History.** The first version used `argsort().argsort()`, which gives identical values *different* ranks depending on their position; identical profiles then received different scores. A test (`test_tie_break_by_candidate_id`) exposed it. **Complexity:** \(O(n \log n)\).

## 6. `adaptive_bounds` - calibrating a long query

#@include engine/features/evidence.py::adaptive_bounds

**Problem.** A long JD text has higher baseline similarity to everything than a one-sentence requirement. A fixed window would make every candidate look relevant (or none). **Approach.** Measure how similar the query is to 12 deliberately *unrelated* anchor sentences; the median of those similarities is the "unrelated" baseline; add a margin of 0.08 and use a width of 0.18. The median, not the mean or maximum, makes the baseline robust to one anchor accidentally being related. **Alternative:** z-scores relative to the candidate pool - rejected because a pool full of relevant candidates would then make good matches look average.

## 7. `weighted_available` - missing-aware means

Shown in Part 3. **Why it matters for fairness:** it is the single mechanism that makes missing optional data neutral across engagement, logistics and experience. **If replaced** by `np.nan_to_num(x) * w` summed, every missing signal would count as zero evidence - 64.6% of candidates would lose points for having no GitHub account (if GitHub were an engagement signal) and 59.6% for having no offer history.

## 8. `Normalizer._signals` handling of sentinels

```python
# excerpt from _signals (engine/ingestion/validation.py)
for name, (kind, lo, hi) in SIGNAL_SPEC.items():
    v = sig.get(name)
    if name in MINUS_ONE_IS_MISSING and v is not None:
        try:
            if float(v) < 0:
                v = None
        except (TypeError, ValueError):
            pass
```

**Problem.** The data documentation says `-1` means "no GitHub linked" or "no offers yet". Left as -1, a GitHub score of -1 would be *clipped to 0* by the range check that follows - turning "unknown" into "worst". Converting it to `None` *before* range checking preserves the meaning. This four-line block is a good example of how data semantics, not just types, must be validated.

## 9. `RunService.query` - server-side filtering

#@include backend/app/services/runs.py::RunService.query

**Problem.** Let the UI filter, search, sort and page up to ~100,000 rows without sending them to the browser. **Statements.** Choose the view (shortlist, held, all); apply each filter as a boolean mask; validate the sort column against an allow-list; for rank sorting, push held rows (rank 0) to the end with a temporary key; slice one page and convert rows with `_row_json`. **Why pandas and not SQL?** The result table is a Parquet file with ~70 columns of floats per row; loading it once into memory (LRU-cached) and filtering with vectorised masks takes 150-270 ms on 99,932 rows. Storing it in SQLite would need a schema per JobSpec (requirement columns differ between runs). **Complexity:** \(O(N)\) per filter plus \(O(N \log N)\) for sorting.

## 10. `validate_text` - the hallucination guard

#@include engine/explanations/validator.py::validate_text

**Problem.** Make it impossible for a generated sentence to name a skill the candidate does not have. **Statements.** `_known_terms()` (cached) compiles a word-boundary regex for every skill name in the taxonomy; each one found in the text must appear in the candidate's skill list or profile text. **Limitation.** It only knows the taxonomy's skill names; a fabricated *company* name would not be caught. That is acceptable here because sentences are assembled only from validated evidence items, and this check is a second line of defence.

## 11. `competition_rows` - satisfying an external validator

#@include engine/ranking/competition.py::competition_rows

**Problem.** The challenge validator requires exactly 100 rows, non-increasing scores and - when scores are equal - candidate ids in ascending order. The engine's own order breaks ties by mandatory coverage and engagement first, so after rounding scores to 6 decimals two rows might be "equal" but in the wrong id order. **Solution.** Re-sort by `(score desc, candidate_id asc)` with a stable sort *after* rounding. Order changes only among exactly tied rounded scores.

## 12. `useAsync` and stale responses

Shown in Part 4. The `seq` counter is the frontend equivalent of a lock: only the most recent request may update state. Removing it produces a classic, hard-to-reproduce UI bug where results "jump back" to an older filter when the network is slow.

## 13. `DatasetService.delete` - shared resources

#@include backend/app/services/datasets.py::DatasetService.delete

**Problem.** Two uploads of the same file share one index directory (same fingerprint). Deleting one dataset must not destroy the other's index. **Statement to notice:** the index directory is removed only if `SELECT 1 FROM datasets WHERE index_dir=?` finds no remaining row. The in-memory `IndexCache` entry is dropped first so no request uses a deleted directory.
