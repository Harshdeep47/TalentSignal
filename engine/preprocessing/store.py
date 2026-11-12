"""Read-side access to a built dataset index."""
from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path

import numpy as np
import orjson
import pandas as pd

from engine.preprocessing.index import INDEX_FORMAT_VERSION
from engine.retrieval.bm25 import BM25Index


class IndexNotFound(FileNotFoundError):
    pass


class DatasetIndex:
    """Lazy loader for the artifacts written by ``build_index``.

    Tables are loaded on first use and kept in memory; full candidate records
    are read from ``records.jsonl`` on demand by byte offset, so the detail
    view never needs the whole file in memory.
    """

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        meta_path = self.dir / "meta.json"
        if not meta_path.exists():
            raise IndexNotFound(f"No index found in {self.dir}")
        self.meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if self.meta.get("format_version") != INDEX_FORMAT_VERSION:
            raise IndexNotFound("Index was built by an incompatible engine version; rebuild it.")

    @property
    def n(self) -> int:
        return int(self.meta["n_candidates"])

    @cached_property
    def candidates(self) -> pd.DataFrame:
        return pd.read_parquet(self.dir / "candidates.parquet")

    @cached_property
    def roles(self) -> pd.DataFrame:
        return pd.read_parquet(self.dir / "roles.parquet")

    @cached_property
    def skills(self) -> pd.DataFrame:
        return pd.read_parquet(self.dir / "skills.parquet")

    @cached_property
    def skill_codes(self) -> tuple[np.ndarray, dict[str, int]]:
        """Integer code per skill row (case-insensitive) and the name->code map.

        Matching requirement skills by integer code is much faster than
        comparing strings across ~1M skill rows.
        """
        cat = pd.Categorical(self.skills["skill"].str.lower())
        return cat.codes.astype(np.int32), {name: i for i, name in enumerate(cat.categories)}

    @cached_property
    def texts(self) -> pd.DataFrame:
        return pd.read_parquet(self.dir / "texts.parquet")

    @cached_property
    def integrity(self) -> pd.DataFrame:
        return pd.read_parquet(self.dir / "integrity.parquet")

    @cached_property
    def quality(self) -> dict:
        return json.loads((self.dir / "quality.json").read_text(encoding="utf-8"))

    @cached_property
    def embeddings(self) -> np.ndarray | None:
        path = self.dir / "embeddings.npy"
        return np.load(path).astype(np.float32) if path.exists() else None

    @cached_property
    def bm25(self) -> BM25Index:
        return BM25Index.load(self.dir)

    @cached_property
    def offsets(self) -> np.ndarray:
        return np.load(self.dir / "offsets.npy")

    @cached_property
    def id_to_idx(self) -> dict[str, int]:
        return {cid: i for i, cid in enumerate(self.candidates["candidate_id"].tolist())}

    def record(self, idx: int) -> dict:
        """Full normalised record for row ``idx``."""
        with open(self.dir / "records.jsonl", "rb") as f:
            f.seek(int(self.offsets[idx]))
            return orjson.loads(f.readline())

    def record_by_id(self, candidate_id: str) -> dict | None:
        idx = self.id_to_idx.get(candidate_id)
        return None if idx is None else self.record(idx)

    def flags_for(self, idx: int) -> list[dict]:
        df = self.integrity
        rows = df[df["idx"] == idx]
        return [
            {"code": r.code, "severity": r.severity, "title": r.title, "detail": r.detail,
             "evidence": json.loads(r.evidence)}
            for r in rows.itertuples()
        ]
