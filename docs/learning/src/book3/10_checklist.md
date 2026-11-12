# Final Mastery Checklist

Tick each item only when you can explain it aloud, without notes, to someone who asks "why?" twice.

## Problem and product
- [ ] Why keyword search fails in both directions (stuffing, plain language), with the measured keyword-count result.
- [ ] The difference between a search engine, an ATS, a recommender and TalentSignal.
- [ ] Why the score is not a probability, and why TalentSignal is decision support.

## Architecture
- [ ] The three layers and the rule that the engine has no web dependencies.
- [ ] Precompute versus rank; why the index is named by a full-file fingerprint.
- [ ] The request lifecycle of `GET /api/runs/{id}/results`.
- [ ] Background jobs, polling, cancellation, and what happens on restart.
- [ ] Where each kind of data is stored (SQLite, index directory, run Parquet) and why.

## Data
- [ ] The candidate schema and which fields are scored, displayed, or never used.
- [ ] Raw data vs processed data vs features.
- [ ] Why `-1` becomes `None`, and the missing-aware mean.
- [ ] The unique-segment optimisation and its numbers (44 descriptions, 5,802 segments).

## Job understanding
- [ ] Section classification, concept detection, importance weights (1.0 / 0.5 / 0.35).
- [ ] What the experience, location, notice and condition extractors find in the reference JD.
- [ ] Why the review step exists (the Elasticsearch example).

## Ranking mathematics
- [ ] Title relevance, affinity, trust (0.3 + 0.7·rel) and credibility (0.5 + 0.5·rel).
- [ ] Skill strength: level, usage \(1 - e^{-m/18}\), 0.35 floor, assessment blend; why max not sum.
- [ ] Text evidence: phrase hit 0.75, calibrated similarity, noisy-OR, trust and recency.
- [ ] Coverage by noisy-OR and its three properties.
- [ ] BM25 formula, \(k_1\), \(b\), why a percentile, and the ablation result.
- [ ] Embeddings, cosine, calibration windows and the anchor-based per-query window.
- [ ] Experience band piecewise function; engagement and logistics sub-signals.
- [ ] Weighted sum with normalisation and re-normalisation; policy factors; eligibility gates; deterministic ordering.

## Worked example
- [ ] Reproduce Asha's 0.911 from her components and weights.
- [ ] Explain why Ravi (0.448) outranks Meera (0.387), and which changes do and do not fix it.

## Explanations and integrity
- [ ] How evidence pointers make explanations consistent with scores.
- [ ] Both validation layers and the false positive that led to splitting the summary.
- [ ] Integrity checks, severities, the 68 critical findings, and what cannot be detected.
- [ ] False positives vs false negatives with examples.

## Performance
- [ ] The measured numbers: 137 s build / 1.99 GB, 2.85 s scoring, 150-270 ms queries, 12 s competition step.
- [ ] Sparse matrices: why 2.2 GB dense becomes 213 MB.
- [ ] What would break first at 1 million candidates (honestly, not benchmarked).

## Evaluation
- [ ] Precision, recall, AP, NDCG - definitions and a hand calculation.
- [ ] Proxy labels, their circularity, and why label-free tests matter.
- [ ] The systems table, including where the reference implementation wins and why.
- [ ] At least four ablation results.

## Engineering
- [ ] Three code pieces in detail: `best_per_group`, `requirement_evidence`, `RunService.query`.
- [ ] Upload security, path allow-listing, formula injection, CSP, parameterised SQL.
- [ ] Why sessions are not authentication.
- [ ] How to run every test suite and the evaluation, and how to debug a surprising rank.

## Judgement
- [ ] Three limitations, each with user impact, a fix and its trade-off.
- [ ] What you would do with another month, and why in that order.
- [ ] One example where measurement overruled intuition (the rejected facet-semantic experiment).
