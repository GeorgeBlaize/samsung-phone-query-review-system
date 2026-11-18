"""Vector retriever over spec chunks.

Backends:
  * tfidf (default) – scikit-learn, zero model download, works everywhere
  * sentence-transformers – dense embeddings (all-MiniLM-L6-v2 by default)
Both expose the same `search()` API with optional phone / category filters.
"""
from __future__ import annotations

import logging
from typing import Iterable

import numpy as np

from app.config import settings
from app.rag.documents import LOW_VALUE_CATEGORIES, Chunk

log = logging.getLogger(__name__)


class _TfidfEncoder:
    def __init__(self, corpus: list[str]):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, token_pattern=r"(?u)\b\w[\w.+]*\b")
        self.matrix = self.vectorizer.fit_transform(corpus)

    def doc_vectors(self):
        return self.matrix

    def encode(self, texts: list[str]):
        return self.vectorizer.transform(texts)


class _DenseEncoder:
    def __init__(self, corpus: list[str], model_name: str):
        from sentence_transformers import SentenceTransformer  # optional dependency

        self.model = SentenceTransformer(model_name)
        self.matrix = self.model.encode(corpus, normalize_embeddings=True)

    def doc_vectors(self):
        return self.matrix

    def encode(self, texts: list[str]):
        return self.model.encode(texts, normalize_embeddings=True)


class SpecRetriever:
    def __init__(self, chunks: list[Chunk], backend: str | None = None):
        self.chunks = chunks
        backend = backend or settings.embedding_backend
        corpus = [c.text for c in chunks] or [""]
        self.encoder = None
        if backend == "sentence-transformers":
            try:
                self.encoder = _DenseEncoder(corpus, settings.embedding_model)
                self.backend = "sentence-transformers"
            except Exception as exc:  # missing package / no network
                log.warning("sentence-transformers unavailable (%s); falling back to TF-IDF", exc)
        if self.encoder is None:
            self.encoder = _TfidfEncoder(corpus)
            self.backend = "tfidf"

    def _scores(self, query: str) -> np.ndarray:
        q = self.encoder.encode([query])
        docs = self.encoder.doc_vectors()
        sims = docs @ q.T
        sims = sims.toarray() if hasattr(sims, "toarray") else np.asarray(sims)
        return sims.ravel()

    def search(
        self,
        query: str,
        k: int | None = None,
        phone_ids: Iterable[int] | None = None,
        categories: Iterable[str] | None = None,
    ) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        k = k or settings.retrieval_top_k
        scores = self._scores(query)
        allowed_phones = set(phone_ids) if phone_ids else None
        boost = {c.lower() for c in categories} if categories else set()
        results = []
        for chunk, score in zip(self.chunks, scores):
            if allowed_phones is not None and chunk.phone_id not in allowed_phones:
                continue
            s = float(score)
            if chunk.category.lower() in boost:
                s += 0.25
            if chunk.category in LOW_VALUE_CATEGORIES:
                s -= 0.1
            results.append((chunk, s))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]

    def chunks_for(self, phone_id: int, categories: Iterable[str]) -> list[Chunk]:
        wanted = [c.lower() for c in categories]
        found = [c for c in self.chunks if c.phone_id == phone_id and c.category.lower() in wanted]
        return sorted(found, key=lambda c: wanted.index(c.category.lower()))
