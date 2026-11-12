# Mock Technical Interviews

Three complete rounds. Practise aloud, ideally with someone reading the interviewer's lines. The evaluation criteria at the end of each round are what a fair interviewer would look for.

## Round 1 - Beginner project discussion (20 minutes)

**Q1. Tell me about the project.** *Ideal:* the 1-minute introduction (Part 1). **Follow-up:** "Who is it for?" → "Recruiters choosing whom to read first; it's decision support, not an automatic hiring system."

**Q2. What was the hardest part?** *Ideal:* "Making keyword stuffing ineffective without losing plain-language candidates. Taking the maximum over skills instead of the sum, and scaling evidence by how relevant the job title is, solved the first; embeddings help the second, but not fully - candidates with generic titles are still under-rated." **Follow-up:** "How did you notice?" → "A worked example where a stuffer outranked a plain-language engineer in a three-person pool."

**Q3. What is an embedding?** *Ideal:* "A vector representing a text's meaning; similar meanings are close. I use a small local model, 384 numbers per text, and cosine similarity."

**Q4. What does the score mean?** *Ideal:* "A weighted summary of evidence between 0 and 1 - not a probability of being hired."

**Q5. How did you test it?** *Ideal:* "63 automated tests plus an evaluation script; I can name tests that guard against stuffing, missing data and hallucinated explanations."

**Q6. What would you do differently?** *Ideal:* pick one limitation and its trade-off.

**Evaluation criteria.** Clear problem statement; correct, simple definitions; mentions decision support and limitations unprompted; no inflated claims.

## Round 2 - Intermediate full-stack and ML engineering (45 minutes)

**Q1. Walk me through what happens when the recruiter clicks "Rank candidates".** *Ideal:* `POST /api/runs` → `RunService.create` inserts a queued run and submits a job → `score_pool` in a thread → result table to Parquet → status ready; browser polls `GET /api/runs/{id}`, then fetches one page from `GET /api/runs/{id}/results`. **Follow-up:** "Why not compute in the request?" → latency and timeouts; progress and cancellation.

**Q2. How is the requirement score computed?** *Ideal:* best matching skill (level × usage, blended with assessment) × credibility; text evidence (phrase hit and calibrated similarity, noisy-OR) × trust × recency; coverage by noisy-OR; weighted mean over requirements. **Follow-up:** "Why noisy-OR rather than an average?" → bounded, rewards corroboration, a weak source can't reduce a strong one.

**Q3. How do you avoid sending 100,000 rows to the browser?** *Ideal:* server-side filtering and paging from a cached Parquet table; at most 200 rows; 150-270 ms per query on 99,932 rows.

**Q4. How do you handle stale responses in React?** *Ideal:* request counter in `useAsync`; `alive` flags in effects.

**Q5. How do you handle missing data?** *Ideal:* missing-aware means; measured effect −0.007; one exception (relocation).

**Q6. How did you calibrate cosine similarity?** *Ideal:* measured distributions (unrelated 0.41-0.55, matches 0.75-0.85) → window [0.62, 0.80]; per-query window for the long JD text using unrelated anchor sentences.

**Q7. Compute NDCG@5 for labels [3, 2, 0, 1, 3] against pool [3, 3, 2, 1, 0, 0].** *Ideal:* 0.901 with the steps in Part 4.

**Q8. What does your evaluation say, honestly?** *Ideal:* proxy composite 0.951 vs reference 0.982, the reasons, and the label-free results.

**Evaluation criteria.** Correct end-to-end flow with real component names; formulas stated precisely; trade-offs discussed; numbers quoted accurately; calculation done correctly and explained.

## Round 3 - Advanced system design and ranking-engine defence (60 minutes)

**Q1. Design this for a company with 5 million candidates and 200 recruiters.** *Ideal structure:* requirements (latency per query, freshness of candidate data, privacy, fairness audits) → batch precompute (distributed parsing, GPU embeddings, per-segment caching) → retrieval stage (ANN over description embeddings + BM25, top 20,000-50,000) → full evidence scoring on the candidates → result tables in object storage → API with auth, PostgreSQL, queue → feedback capture → offline/online evaluation loop. **Follow-up:** "Where are the bottlenecks?" → unique-text growth, index rebuilds on data changes (incremental indexing by fingerprint per record), cross-tenant isolation.

**Q2. Your title relevance is a single point of failure. Defend it or change it.** *Ideal:* defend its purpose (credibility under manipulation), concede the plain-language weakness with the measured example, propose description-informed relevance with a guard (only when skills and descriptions agree, and capped), and insist on measuring against the adversarial set before shipping.

**Q3. Why not just train a model?** *Ideal:* no labels; proxies would teach the heuristics back; plan for implicit feedback with position-bias correction; LambdaMART on the seven components first, because it is interpretable via feature importance and easy to compare with the current weights.

**Q4. A recruiter complains: "the top candidate has never worked with Elasticsearch".** *Ideal:* open the explanation; check the requirement's evidence (skill or text?); check the JobSpec (was Elasticsearch a separate requirement, or merged into "vector databases" by the taxonomy?); fix the spec or taxonomy; re-run; if the explanation claimed something absent, that's a validator bug - add a test.

**Q5. Prove your explanations cannot hallucinate.** *Ideal:* they can't claim skills absent from the record because (1) evidence items are built from pointers recorded during scoring, (2) each item is re-verified field by field, (3) the claims sentence is scanned for any taxonomy skill name not in the record, with a fallback sentence. Concede the boundary: the text scan covers taxonomy skill names, not arbitrary words; measured 0 unsupported mentions in 200.

**Q6. How do you make it fair?** *Ideal:* bias channels (features, proxies, defaults, feedback loops) and what the code does for each; what cannot be claimed (no group audit); what production needs (lawful audit data, review workflow, documentation for candidates).

**Q7. What would make you roll back a change?** *Ideal:* a drop in top-10 overlap stability, a rise in stuffer rank, any unsupported claim in the explanation audit, a latency regression, or a proxy improvement that comes only from ignoring a JD requirement (the engagement example).

**Evaluation criteria.** Structured design with stated assumptions; scaling plan tied to measured bottlenecks; ability to defend *and* criticise own design; concrete evaluation and rollback criteria; no invented numbers.
