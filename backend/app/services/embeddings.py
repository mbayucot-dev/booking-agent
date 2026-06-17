"""Text embeddings + cosine similarity for semantic preference matching.

Real embeddings via OpenAI when a key is configured (cleaner bios embedded on
write; the customer preference embedded once per request). Without a key the
embedder returns None, so the preference signal contributes 0 and selection
degrades gracefully to the structured rules.
"""

from __future__ import annotations

from math import sqrt
from typing import Protocol

from ..config import Settings, get_settings


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sqrt(sum(x * x for x in a))
    nb = sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class Embedder(Protocol):
    def embed(self, text: str | None) -> list[float] | None: ...


class NullEmbedder:
    """No embeddings (no key) — semantic matching is disabled, rules still run."""

    def embed(self, text: str | None) -> list[float] | None:
        return None


class OpenAIEmbedder:
    """OpenAI embeddings with a per-instance vector cache and a single reused
    client, plus bounded timeout/retries so a slow call can't hang a worker."""

    def __init__(
        self, model: str = "text-embedding-3-small", timeout: float = 10.0, max_retries: int = 2
    ):
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self._cache: dict[str, list[float]] = {}
        self._client = None  # built lazily on first use, then reused

    def _get_client(self):
        if self._client is None:
            from langchain_openai import OpenAIEmbeddings

            self._client = OpenAIEmbeddings(
                model=self.model, timeout=self.timeout, max_retries=self.max_retries
            )
        return self._client

    def embed(self, text: str | None) -> list[float] | None:
        if not text:
            return None
        if text in self._cache:
            return self._cache[text]
        try:
            vec = self._get_client().embed_query(text)
        except Exception:
            return None
        self._cache[text] = vec
        return vec


def build_embedder(settings: Settings | None = None) -> Embedder:
    settings = settings or get_settings()
    if settings.use_real_openai:
        return OpenAIEmbedder(settings.embedding_model)
    return NullEmbedder()
