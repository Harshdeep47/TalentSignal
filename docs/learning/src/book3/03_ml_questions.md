# AI, ML and NLP Questions

Each topic follows the same six steps: **concept from scratch**, **simple example**, **connection to TalentSignal** (marked *Implemented*, *Implemented in evaluation*, or *Related - not used*), **strong interview answer**, **common misconceptions**, **follow-up questions**. Levels: (B) beginner, (I) intermediate, (A) advanced.

## (B) TF-IDF

**Concept.** A way to weigh words in a document: frequent in *this* document (term frequency, tf) but rare across *all* documents (inverse document frequency, idf). \(\mathrm{tfidf}(t, d) = \mathrm{tf}(t, d) \cdot \log(N / \mathrm{df}(t))\).

**Example.** In a pool of profiles, "engineer" appears everywhere (low idf); "pgvector" appears in few (high idf). A profile mentioning pgvector twice gets a high weight for that term.

**TalentSignal.** *Related - not used for scoring.* The original reference implementation used TF-IDF cosine similarity; TalentSignal replaced it with BM25 plus embeddings.

**Strong answer.** "TF-IDF is the classic term weighting. I used BM25 instead because it adds two things TF-IDF lacks: diminishing returns for repeated terms and normalisation for document length - both matter when candidates write very different amounts."

**Misconceptions.** That TF-IDF captures meaning (it does not - "ranking" and "ordering" are unrelated to it); that higher raw TF-IDF always means more relevant (long documents accumulate weight).

**Follow-ups.** *What does the log in idf do?* Compresses the range so very rare terms do not dominate. *How would you use TF-IDF with cosine?* Represent the query and documents as TF-IDF vectors and compare angles.

## (I) BM25

**Concept.** \(\mathrm{BM25} = \sum_t \mathrm{idf}(t) \frac{\mathrm{tf}(k_1+1)}{\mathrm{tf} + k_1(1 - b + b\,|d|/\mathrm{avgdl})}\). \(k_1\) controls saturation (repeated terms add less and less), \(b\) controls length normalisation.

**Example.** With \(k_1 = 1.2\), the first occurrence of a term contributes \(\mathrm{idf} \times 2.2/2.2 = \mathrm{idf}\) (for an average-length document) and the second only about \(0.38 \times\) idf more.

**TalentSignal.** *Implemented* (`engine/retrieval/bm25.py`): unigrams and bigrams, English stop words, \(k_1 = 1.2\), \(b = 0.75\); the query-independent part precomputed into a sparse matrix; scores turned into a tie-aware percentile; 5% weight.

**Strong answer.** "BM25 is the standard lexical baseline. I precompute the saturation term per document, so a query is one sparse matrix-vector product over 100,000 candidates. Because raw BM25 has no fixed scale, the component is the candidate's percentile among matches. Honestly, ablation showed it didn't change this job's top 100 - all top candidates saturate it - so it's kept small, mainly for custom requirements outside the taxonomy."

**Misconceptions.** "BM25 is outdated" - it remains a strong baseline and part of most hybrid systems. "Percentile is the same as normalisation" - it is relative to the pool.

**Follow-ups.** *Why bigrams?* So "vector search" is a feature. *What happens at b = 0?* No length normalisation.

## (B) Cosine similarity

**Concept.** Similarity of two vectors as the cosine of the angle between them: \(\frac{u \cdot v}{\lVert u\rVert \lVert v\rVert}\), from −1 to 1; it ignores length.

**Example.** \(u = (1, 2, 2)\), \(v = (2, 1, 2)\): \(u \cdot v = 8\), both lengths are 3, cosine = \(8/9 = 0.889\).

**TalentSignal.** *Implemented*: embeddings are L2-normalised, so cosine is a dot product (`self.emb @ vector`).

**Strong answer.** "With unit vectors, cosine equals the dot product, so scoring all unique texts against a query is a single matrix-vector multiplication."

**Misconceptions.** That 0.5 means "50% similar" - for sentence embeddings, unrelated texts already score ~0.4-0.55 with this model, which is why calibration was needed.

**Follow-ups.** *Cosine vs Euclidean distance on unit vectors?* \(\lVert u - v\rVert^2 = 2 - 2\cos\), so they rank identically.

## (I) Embeddings and semantic search

**Concept.** A neural model maps text to a dense vector so that texts with similar meaning are close. *Semantic search* retrieves by vector closeness rather than shared words.

**Example.** "Built systems that connect users to the most relevant matches" lands near "search and ranking systems" despite sharing almost no words.

**TalentSignal.** *Implemented* for scoring (not as a retrieval index): bge-small-en-v1.5, 384-d, offline; unique segments embedded at index time; requirement sentences and the JD focus embedded at scoring time; calibrated similarities feed text evidence and the semantic component. *Related - not used:* an approximate-nearest-neighbour index (FAISS etc.); every candidate is scored, so none is needed at 100,000.

**Strong answer.** "Embeddings let me catch plain-language candidates. I calibrate similarities using measured distributions rather than treating them as probabilities, and I weight a description's similarity by how credible its job title makes it."

**Misconceptions.** "Embeddings understand the job" - they measure textual similarity and are fooled by style (all summaries looked alike: 0.70-0.81). "Bigger model is always better" - CPU latency and licence matter.

**Follow-ups.** *Bi-encoder vs cross-encoder?* A bi-encoder embeds query and document separately (fast, precomputable); a cross-encoder reads them together (more accurate, too slow for 100,000 per query) - good for re-ranking a top list. *How would you detect embedding drift?* Monitor similarity distributions over time; re-run the calibration script.

## (I) Vector similarity at scale

**Concept.** Exact similarity against \(n\) vectors costs \(O(n \cdot d)\). Approximate nearest neighbour (ANN) indexes (HNSW graphs, IVF clustering, product quantisation) trade a little recall for much speed.

**TalentSignal.** *Related - not used.* At 5,802 unique segments, an exact matrix product takes milliseconds. ANN would matter for millions of unique texts or for pre-selecting candidates.

**Strong answer.** "I chose exact search because the unique-segment trick made it cheap. At larger scale I would pre-select with an ANN index and then run the full evidence scoring on the shortlist."

## (B) Feature engineering

**Concept.** Turning raw data into numbers a model can combine - here, numbers in [0, 1] with clear meaning.

**TalentSignal.** *Implemented*: title relevance, recency, trust, credibility, skill strength, coverage, band fit, engagement sub-signals, logistics sub-signals. Each is documented with its formula (Book 1, Part 6).

**Strong answer.** "Most of the work was in features that resist manipulation: max-instead-of-sum skill evidence, usage-aware claims, credibility from titles, trust-weighted text evidence."

**Misconception.** "More features always help" - the semantic facet experiment added a feature and *lowered* the proxy score.

## (I) Ranking systems and recommendation systems

**Concept.** A ranking system orders items for a query; a recommender orders items for a user based on behaviour or content. Both are evaluated mostly at the top of the list.

**TalentSignal.** *Implemented:* query-dependent ranking (the JobSpec is the query). *Related - not used:* collaborative filtering (no interaction data).

**Strong answer.** "This is content-based ranking with hand-designed relevance features. Recommender techniques would become relevant once recruiter feedback exists - for example 'recruiters who shortlisted A also shortlisted B'."

## (B) Weighted scoring and normalisation

**Concept.** A weighted sum combines features: \(\sum_c w_c x_c\). *Normalisation* puts features (or weights) on comparable scales.

**TalentSignal.** *Implemented:* every component in [0, 1] on an *absolute* scale where possible; weights normalised to sum to 1 and re-normalised when a component is unavailable; BM25 is the exception (percentile).

**Strong answer.** "I avoided min-max normalisation over the pool because one outlier shifts everyone's score and scores become incomparable between pools. Absolute scales mean a 0.8 coverage means the same in a 50-candidate upload and a 100,000-candidate pool."

**Misconceptions.** That weights are importance in an absolute sense - they are relative shares after normalisation.

**Follow-ups.** *Why multiply policy factors rather than subtract?* A factor scales the whole score so no amount of other evidence compensates for a declared near-disqualifier.

## (B) Precision, recall, precision@k

**Concept.** Precision = relevant retrieved / retrieved. Recall = relevant retrieved / all relevant. Precision@k looks only at the first k results.

**Example.** 10 retrieved, 6 relevant among them, 8 relevant in the pool: precision 0.6, recall 0.75.

**TalentSignal.** *Implemented in evaluation* (`precision_at`, "relevant" = proxy label ≥ 3).

**Strong answer.** "For shortlists, precision at the top matters most - a recruiter reads the first page."

## (I) MAP - mean average precision

**Concept.** Average precision (AP) averages precision@i over the positions i where a relevant item appears, divided by the number of relevant items (TalentSignal uses min(R, k)). MAP averages AP over queries.

**Example.** Relevant items at positions 1 and 5 of the top 5, two relevant items in the pool: \(\mathrm{AP@5} = (1/1 + 2/5)/2 = 0.7\).

**TalentSignal.** *Implemented in evaluation* (`average_precision`); with one job, "MAP" is the AP of that query.

## (I) NDCG

**Concept.** Discounted cumulative gain rewards relevant items more when they are higher: \(\mathrm{DCG@k} = \sum_{i \le k} \frac{2^{rel_i} - 1}{\log_2(i+1)}\). NDCG divides by the DCG of the ideal ordering so the result lies in [0, 1].

**Example.** Ranked labels [3, 2, 0, 1, 3], pool labels [3, 3, 2, 1, 0, 0]: DCG@5 = 12.03, ideal DCG@5 = 13.35, NDCG@5 = 0.901 (worked step by step in Part 4).

**TalentSignal.** *Implemented in evaluation*; the ideal ordering is computed over the **whole labelled pool**, so missing a strong candidate is penalised.

**Strong answer.** "NDCG@10 carries 50% of the competition composite because the first page dominates real use."

**Misconceptions.** That NDCG compares to a perfect list of what *you* returned - it compares to the best possible list from the pool.

## (I) MRR - mean reciprocal rank

**Concept.** \(1/\text{rank of the first relevant result}\), averaged over queries.

**TalentSignal.** *Related - not used.* It suits "find one right answer" tasks; shortlisting wants several good candidates, which NDCG and MAP capture better.

## (A) Evaluation datasets and proxy labels

**Concept.** Ranking evaluation needs relevance judgements. Without them, you can use proxy labels, synthetic tests, or online feedback.

**TalentSignal.** *Implemented:* hand-graded proxy labels for 44 description templates adjusted by JD conditions; label-free adversarial, stability and grounding tests.

**Strong answer.** "Proxy labels are circular to a degree - the scorer reads the same descriptions - so I used them only to compare variants, and relied on label-free tests for robustness claims. With real use I would collect recruiter actions as implicit labels and run an A/B test on shortlist acceptance."

**Follow-ups.** *How would you get real labels cheaply?* Pairwise judgements from recruiters on disagreements between two rankers; implicit feedback (shortlisted, contacted, interviewed) with position-bias correction.

## (A) Bias and fairness

**Concept.** A ranking is unfair if it systematically disadvantages groups for reasons unrelated to the job, through features, proxies, defaults or feedback loops.

**TalentSignal.** *Implemented safeguards:* no protected attributes; institution prestige never used; missing data neutral; work-authorization condition only for explicit non-relocators; popularity signals excluded; editable policies. *Not done:* group-level outcome audits (no demographic data).

**Strong answer.** "I designed against known bias channels and measured what I could - for example that missing optional data doesn't move scores. I can't claim the outcomes are fair across groups, because the data has no group attributes to audit with; in production that audit is essential."

**Misconceptions.** "Removing protected attributes makes a model fair" - proxies (location, school, gaps) can encode them.

## (A) Explainable AI

**Concept.** Making model outputs understandable: global (how the model works) and local (why this output).

**TalentSignal.** *Implemented:* the model is interpretable by construction (weighted bounded components); local explanations are built from the exact evidence used; validated against the record; differentiators against neighbouring ranks.

**Strong answer.** "Post-hoc explainers like SHAP approximate a black box. Here the model itself is the explanation, so the explanation can't disagree with the score - and a validator guarantees no claimed skill is absent from the record."
