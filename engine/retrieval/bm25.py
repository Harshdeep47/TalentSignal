"""Okapi BM25 over candidate documents, implemented with sparse matrices.

For a query q and document d:

    BM25(q, d) = sum_t  idf(t) * tf(t,d) * (k1 + 1) / (tf(t,d) + k1 * (1 - b + b * |d| / avgdl))
    idf(t)     = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

The tf-saturation part does not depend on the query, so it is precomputed
once per dataset into a sparse matrix W (candidates x terms). Scoring a query
is then a single sparse matrix-vector product ``W @ (idf * query_weights)``,
which takes milliseconds for 100K candidates.

Candidate documents are assembled from *unique text segments* (headline,
summary, role titles, role descriptions, skill names). Each unique segment is
tokenised once; a sparse incidence matrix A (candidates x segments) then gives
term frequencies as ``A @ T``. On templated data this is dramatically cheaper
than tokenising 100K full documents, and on unique data it costs the same.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import CountVectorizer

K1 = 1.2
B = 0.75
TOKEN_PATTERN = r"(?u)\b[a-z0-9][a-z0-9+#]*(?:[-.][a-z0-9+#]+)*\b"
MAX_FEATURES = 150_000


def make_vectorizer(vocabulary: dict[str, int] | None = None) -> CountVectorizer:
    return CountVectorizer(lowercase=True, token_pattern=TOKEN_PATTERN, ngram_range=(1, 2),
                           stop_words="english", max_features=None if vocabulary else MAX_FEATURES,
                           vocabulary=vocabulary, dtype=np.float32)


class BM25Index:
    def __init__(self, weights: sparse.csr_matrix, idf: np.ndarray, vocabulary: dict[str, int]):
        self.weights = weights
        self.idf = idf
        self.vocabulary = vocabulary
        self._vectorizer = make_vectorizer(vocabulary)

    @classmethod
    def build(cls, segment_texts: list[str], incidence: sparse.csr_matrix) -> "BM25Index":
        vec = make_vectorizer()
        seg_tf = vec.fit_transform(segment_texts).tocsr()          # segments x terms
        tf = (incidence @ seg_tf).tocsr().astype(np.float32)       # candidates x terms
        n = tf.shape[0]
        df = np.bincount(tf.indices, minlength=tf.shape[1]).astype(np.float64)
        idf = np.log1p((n - df + 0.5) / (df + 0.5)).astype(np.float32)
        dl = np.asarray(tf.sum(axis=1)).ravel()
        avgdl = float(dl.mean()) if n else 1.0
        norm = K1 * (1 - B + B * dl / max(avgdl, 1e-9))
        rows = np.repeat(np.arange(n), np.diff(tf.indptr))
        data = tf.data
        tf.data = (data * (K1 + 1) / (data + norm[rows])).astype(np.float32)
        vocab = {k: int(v) for k, v in vec.vocabulary_.items()}
        return cls(tf, idf, vocab)

    def query_vector(self, weighted_terms: list[tuple[str, float]]) -> np.ndarray:
        """Turn (text, weight) pairs into an idf-weighted query vector."""
        q = np.zeros(len(self.vocabulary), dtype=np.float32)
        for text, w in weighted_terms:
            row = self._vectorizer.transform([text])
            for j in row.indices:
                q[j] = max(q[j], w)
        return q * self.idf

    def score(self, weighted_terms: list[tuple[str, float]]) -> np.ndarray:
        q = self.query_vector(weighted_terms)
        if not q.any():
            return np.zeros(self.weights.shape[0], dtype=np.float32)
        return np.asarray(self.weights @ q).ravel()

    def save(self, directory: Path) -> None:
        sparse.save_npz(directory / "bm25_weights.npz", self.weights, compressed=False)
        np.save(directory / "bm25_idf.npy", self.idf)
        (directory / "bm25_vocab.json").write_text(json.dumps(self.vocabulary), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> "BM25Index":
        w = sparse.load_npz(directory / "bm25_weights.npz").tocsr()
        idf = np.load(directory / "bm25_idf.npy")
        vocab = json.loads((directory / "bm25_vocab.json").read_text(encoding="utf-8"))
        return cls(w, idf, vocab)
