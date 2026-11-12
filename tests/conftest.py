import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from engine.jd.parser import parse_job_description  # noqa: E402
from engine.preprocessing.index import build_index  # noqa: E402
from engine.preprocessing.store import DatasetIndex  # noqa: E402
from engine.retrieval.embeddings import get_embedder  # noqa: E402
from factories import standard_pool, write_jsonl  # noqa: E402

REDROB_JD = ROOT / "engine" / "resources" / "jobs" / "redrob_senior_ai_engineer.txt"


@pytest.fixture(scope="session")
def redrob_spec():
    return parse_job_description(REDROB_JD.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def pool_index(tmp_path_factory) -> DatasetIndex:
    """Small index WITHOUT embeddings: fast and independent of the model files."""
    d = tmp_path_factory.mktemp("pool")
    src = write_jsonl(standard_pool(), d / "pool.jsonl")
    build_index(src, d / "ix", embed=False)
    return DatasetIndex(d / "ix")


@pytest.fixture(scope="session")
def semantic_index(tmp_path_factory) -> DatasetIndex:
    if get_embedder() is None:
        pytest.skip("Local embedding model not available")
    d = tmp_path_factory.mktemp("sem")
    src = write_jsonl(standard_pool(n_filler=20), d / "pool.jsonl")
    build_index(src, d / "ix", embed=True)
    return DatasetIndex(d / "ix")
