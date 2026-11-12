"""Local sentence-embedding model wrapper.

Model: BAAI/bge-small-en-v1.5 (MIT licence, 33M parameters, 384-d vectors,
~130 MB). Chosen because it runs on CPU at a usable speed, is small enough to
ship with the app, and ranks well on retrieval benchmarks for its size.

The model is loaded only from a local directory and with Hugging Face
offline mode forced on, so ranking never makes network calls. If the model is
not present the engine still works: semantic components are disabled and the
remaining weights are re-normalised (recorded in the run metadata).

Vectors are L2-normalised, so cosine similarity is a plain dot product.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Callable

import numpy as np

DEFAULT_MODEL_NAME = "bge-small-en-v1.5"
log = logging.getLogger(__name__)
_lock = threading.Lock()
last_error: str | None = None
_cache: dict[str, "Embedder"] = {}


def default_model_dir() -> Path:
    env = os.environ.get("TALENTSIGNAL_MODEL_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "artifacts" / "models" / DEFAULT_MODEL_NAME


class Embedder:
    def __init__(self, model_dir: Path):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        from sentence_transformers import SentenceTransformer  # heavy import, done lazily
        import torch

        torch.set_num_threads(max(1, os.cpu_count() or 1))
        self.model_dir = model_dir
        self.name = model_dir.name
        self.model = SentenceTransformer(str(model_dir), device="cpu", local_files_only=True)
        getter = getattr(self.model, "get_embedding_dimension", None) or self.model.get_sentence_embedding_dimension
        self.dim = int(getter())
        # Query-side cache: requirement prototypes and anchor texts repeat
        # across ranking runs, so their vectors are memoised (bounded size).
        self._cache: dict[str, np.ndarray] = {}
        self._cache_lock = threading.Lock()

    def encode(self, texts: list[str], batch_size: int = 64,
               progress: Callable[[int, int], None] | None = None,
               should_cancel: Callable[[], bool] | None = None) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        # Sorting by length keeps batches uniform, which cuts padding work:
        # one long text in a batch forces every short text to its length.
        order = np.argsort([len(t) for t in texts])
        for start in range(0, len(texts), batch_size):
            if should_cancel and should_cancel():
                raise InterruptedError("cancelled")
            idx = order[start:start + batch_size]
            vecs = self.model.encode([texts[i] for i in idx], batch_size=batch_size,
                                     normalize_embeddings=True, show_progress_bar=False)
            out[idx] = vecs
            if progress:
                progress(min(start + batch_size, len(texts)), len(texts))
        return out

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        """Encode short query-side texts with memoisation and length bucketing."""
        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if missing:
            vecs = self.encode(missing, batch_size=8)
            with self._cache_lock:
                if len(self._cache) > 5000:
                    self._cache.clear()
                self._cache.update(zip(missing, vecs))
        return np.vstack([self._cache[t] for t in texts]) if texts else np.zeros((0, self.dim), np.float32)


def get_embedder(model_dir: Path | None = None) -> Embedder | None:
    """Return a cached embedder, or None if the local model is unavailable."""
    path = Path(model_dir or default_model_dir())
    key = str(path)
    with _lock:
        if key in _cache:
            return _cache[key]
        if not (path / "config.json").exists():
            return None
        try:
            emb = Embedder(path)
        except Exception as exc:  # pragma: no cover - environment-specific failure
            global last_error
            last_error = f"{type(exc).__name__}: {exc}"
            log.error("Embedding model at %s failed to load: %s", path, last_error)
            return None
        _cache[key] = emb
        return emb
