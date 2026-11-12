"""TalentSignal ranking engine.

The engine is a plain Python library with no web or UI dependencies. The
backend (FastAPI) and the command-line scripts both call into it.

Main entry points:
    engine.ingestion.readers.iter_records   -- stream candidate files
    engine.preprocessing.index.build_index  -- offline precompute step
    engine.jd.parser.parse_job_description  -- JD text -> editable JobSpec
    engine.ranking.scorer.rank              -- JobSpec + index -> ranked results
    engine.explanations.explain.explain_candidate -- grounded explanation
"""

__version__ = "1.0.0"
