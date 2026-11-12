# Developer Exercises

The exercises increase in difficulty. Try each one before reading the hints and solutions in Appendix A. Always start by running the tests (`.venv/Scripts/python -m pytest`) so you know they pass before your change, and run them again afterwards.

## Level 1 - reading and small changes

**Exercise 1.1 - Trace a number.** Pick any candidate in a run and find, in the code, every step that produced their `logistics` value. Write down the file and function for each step. *Goal: navigate the code from the UI to the engine.*

**Exercise 1.2 - Change a default weight.** Make the default weight of the `engagement` component 0.15 instead of 0.11. Which file? What happens to the other weights' effective shares? Which test, if any, should you update?

**Exercise 1.3 - Add a taxonomy concept.** Add a concept `graph_ml` (label "Graph machine learning", skills `["Graph Neural Networks", "PyTorch Geometric"]`, phrases `["graph neural network", "gnn", "knowledge graph embedding"]`, a semantic sentence). Verify that a JD with "Must have: graph neural networks" now produces a mandatory requirement.

## Level 2 - features across layers

**Exercise 2.1 - New result filter: "open to work only".** Add a query parameter `open_to_work=true` to `GET /api/runs/{id}/results` that keeps only candidates whose `sig_open_to_work_flag` is true, and a checkbox in the filter panel. Add an API test.

**Exercise 2.2 - New export column.** Add the candidate's `highest_degree` to the CSV/XLSX exports.

**Exercise 2.3 - New API endpoint.** Add `GET /api/runs/{id}/summary.txt` that returns a plain-text summary: job title, dataset, counts, and the top 10 candidate ids with scores. Respect session ownership.

**Exercise 2.4 - New frontend component.** On the run page, add a small "Score composition" legend that shows, for the currently selected candidates (when 1-6 are selected), each one's overall score as a mini bar. Reuse `ScoreBar`.

## Level 3 - engine changes with tests

**Exercise 3.1 - New scoring sub-feature: certifications.** Make certifications count as weak skill evidence: a certification whose name contains a requirement phrase (for example "AWS Certified Machine Learning" for an ML requirement) adds evidence of 0.4 to that requirement's skill part. Keep coverage bounded. Write a unit test that shows a certification raises coverage and that ten certifications do not raise it more than one.

**Exercise 3.2 - New ranking test.** Write a test proving that a candidate who is identical to another except for a 90-day notice period ranks lower when the JD prefers 30 days, and equal when the JD states no notice preference.

**Exercise 3.3 - Database field.** Add a `description` (free text) column to `shortlists`, editable through `POST /api/shortlists` and shown on the shortlist page. Consider existing databases.

## Level 4 - design and performance

**Exercise 4.1 - Improve the plain-language weakness.** Book 1, Part 7 showed a plain-language candidate with a generic title ranking below a stuffer in a tiny pool. Propose and implement *one* change, then measure it with `scripts/run_evaluation.py` (composite, top-10 overlap, stuffer rank, plain-language ranks). Keep it only if it helps without hurting stuffing resistance.

**Exercise 4.2 - Faster index build.** Parsing and normalising takes about 17 s for 100,000 records in one process. Design a parallel version (for example splitting the JSONL by byte ranges across processes). What must stay deterministic? Measure before and after.

**Exercise 4.3 - Top-K without a full sort.** `score_pool` sorts all candidates. For a shortlist of 100 out of 1,000,000, sketch how `np.argpartition` could reduce the cost, and why the full sort is still needed for "all eligible" runs and for deterministic tie-breaking.
