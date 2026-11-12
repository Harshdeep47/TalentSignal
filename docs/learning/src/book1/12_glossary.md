# Glossary {.appendix}

Terms are defined as they are used in TalentSignal.

| Term | Meaning |
|---|---|
| Ablation | An experiment that removes one part of a system to measure its contribution |
| Affinity (family affinity) | Hand-set number in [0, 1] saying how transferable experience in one role family is to another |
| As-of date | Reference date for "days since active"; by default the newest activity date in the dataset |
| Assessment | A platform-administered skill test score (0-100); treated as verified evidence |
| BM25 | Keyword-relevance formula with term-frequency saturation and length normalisation |
| Calibration | Mapping raw values (e.g. cosine similarity) onto a meaningful scale |
| Component | One of the seven [0, 1] sub-scores combined into the overall score |
| Constraint / declared condition | A condition the JD states (e.g. consulting-only careers) with a policy: show only, penalise, exclude |
| Cosine similarity | Similarity of two vectors as the cosine of the angle between them; equals the dot product for unit vectors |
| Coverage | Strength of evidence for one requirement, combined by noisy-OR |
| Credibility | Factor (0.5-1.0) scaling skill evidence by the relevance of the candidate's titles |
| CSR matrix | Compressed Sparse Row format: stores only non-zero values of a matrix |
| Embedding | A vector representing the meaning of a text, produced by a neural model |
| Engagement | Component built from platform behaviour (activity, responsiveness, reliability) |
| Evidence completeness | Fraction of trust-relevant fields present; displayed, not scored |
| Feature | A number computed for a specific job from processed data, used in scoring |
| Fingerprint | BLAKE2b hash of every byte of a candidate file; names its index directory |
| Held for review | Not in the shortlist because of a gate or critical finding; still inspectable |
| Honeypot | A deliberately impossible profile planted in the reference dataset |
| Index (dataset index) | Directory of precomputed tables, BM25 matrix and embeddings for one candidate file |
| Integrity finding | Result of a consistency check; critical, warning or info |
| JobSpec | Structured, editable representation of a job description (Pydantic model) |
| JSONL | One JSON object per line; streamable |
| Lexical | Based on exact words (as opposed to semantic meaning) |
| Mandatory coverage | Weighted mean coverage over must-have requirements |
| Missing-aware mean | Weighted mean that ignores unavailable values instead of counting them as 0 |
| NDCG | Normalised Discounted Cumulative Gain - a ranking metric emphasising the top positions |
| Noisy-OR | \(1 - \prod(1 - p_i)\): probability that at least one independent source fires |
| Normaliser | `Normalizer` class that validates and repairs records during ingestion |
| Precompute | Work done once per dataset and saved, so per-job work is cheap |
| Proxy labels | Hand-made stand-in relevance labels; not ground truth |
| Recency | \(e^{-m/48}\) for a role that ended \(m\) months ago |
| Role family | Group of job titles matched by taxonomy patterns |
| ScoredPool | Engine output: ordered table of all candidates plus evidence arrays |
| Semantic | Based on meaning rather than exact words |
| Session id | Random UUID per browser used to separate history (not authentication) |
| Taxonomy | The YAML knowledge base of concepts, skills, phrases, role families and affinities |
| Title relevance | How close a job title is to the role being hired for (0-1) |
| Trust | Factor (0.3-1.0) scaling a role description's evidence by its title's relevance |
| Unique segment | A distinct text (headline, summary, title, description) processed once and shared by id |
