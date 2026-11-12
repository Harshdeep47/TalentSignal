# Resume and Project Presentation

Everything here must stay true to the repository. Do not add user counts, accuracy percentages, deployment claims or company impact that you cannot show.

## A technically accurate project description

> **TalentSignal - explainable candidate ranking platform.** A FastAPI + React/TypeScript application and a Python ranking engine that turns a job description into editable requirements and ranks candidate pools by bounded, evidence-based scoring (skills with usage and assessments, title-trusted career text via BM25 and sentence embeddings, experience, engagement and logistics), with integrity checks and explanations validated against each candidate's record. Runs offline on CPU; scores 100,000 candidates in about 3 seconds after a one-time 2-minute index build.

## Resume bullet examples

Choose three or four; each is backed by a file you can show.

- Built a vectorised evidence-scoring engine (NumPy/SciPy) that ranks 100,000 candidate profiles in 2.85 s on a laptop CPU after a one-time 137 s precompute, by processing 5,802 unique text segments instead of ~500,000 documents.
- Designed manipulation-resistant scoring - max-over-skills evidence, usage-weighted claims and title-based credibility; in a synthetic adversarial test, keyword stuffers with perfect assessments never ranked above 107th of 560.
- Implemented grounded explanations that follow the exact evidence used for scoring and validate every claim against the source record (0 unsupported skill mentions in a 200-explanation audit).
- Built a FastAPI service with background jobs, SQLite/Parquet persistence, server-side paging over ~100,000-row result tables (150-270 ms per query) and six export formats, with upload limits, path allow-listing and spreadsheet formula-injection protection.
- Built an evaluation harness (proxy NDCG/MAP, ablations, weight-perturbation stability, adversarial injection) and used it to reject a feature that reduced ranking quality.
- Built a résumé ingestion pipeline (PDF/DOCX/ZIP) where every extracted value carries a stated/inferred/missing status and its page and line, with recruiter review before ranking; processed 10,000 synthetic résumés in about 3 minutes at under 1 GB peak memory, with zip-bomb, zip-slip and size protections.
- Wrote 102 automated tests (pytest, FastAPI TestClient, Vitest/Testing Library).

!!! warning "Bullets to avoid"
    "Improved hiring accuracy by X%" (never measured), "deployed to production / used by recruiters" (not true), "fair AI" (not audited), "scales to millions" (not benchmarked), "outperforms the baseline" (the reference scores higher on the proxies).

## GitHub README suggestions

The existing `README.md` already has quick start, commands, configuration, measured results and provenance. Improvements worth making:

1. Put two screenshots at the top (results cards and candidate profile) and a 30-second GIF of the ranking flow.
2. Add a "How it works in one diagram" section linking Book 1, Figure 6.1.
3. Add a "Known limitations" section in the README itself, not only in `docs/STATUS.md`.
4. Add a badge-free "Reproduce the numbers" section listing `scripts/run_evaluation.py` and `scripts/smoke_test.py`.
5. State the licence of the repository (none is declared yet) and keep the provenance note about the reference implementation.

## Portfolio description (short)

> I built TalentSignal to explore how to rank people *responsibly*: make every score decomposable, make explanations impossible to fabricate, keep missing data neutral, and measure robustness to manipulation. The most interesting lesson was that the metric I had (proxy labels) disagreed with the job description on availability - optimising it would have made the product worse.

## Demonstration walkthrough (8 minutes)

1. **Dashboard** (30 s) - shared 100,000-candidate dataset, health.
2. **Dataset quality** (1 min) - 68 critical integrity findings; missing-value rates; "missing is neutral".
3. **New ranking** (1.5 min) - load the preset JD, analyse, show must-haves with source sentences and declared conditions; set Top 50.
4. **Results** (1.5 min) - progress, distribution, filters (India, 5+ years, FAISS), card view with summaries, the "Held for review" tab.
5. **Candidate profile** (1.5 min) - score composition table, verified versus self-reported evidence, concerns versus missing information.
6. **Compare and shortlist** (1 min) - compare three; save two with a note; export XLSX and the competition CSV.
7. **Close with evidence** (1 min) - the evaluation report, including where the reference implementation wins.

## Metrics worth measuring before making more claims

| Claim you might want to make | Measurement needed |
|---|---|
| "Saves recruiters time" | time-to-shortlist with and without the tool, in a controlled study |
| "Better shortlists" | recruiter judgements or interview-rate of shortlisted candidates versus a baseline |
| "Fair" | selection-rate ratios across groups, where data is lawfully available |
| "Scales to N" | build time, peak memory and query latency at N |
| "Robust to gaming" | adversarial tests designed by someone other than the author |
