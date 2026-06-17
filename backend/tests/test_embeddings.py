"""Embeddings + cosine (used by semantic preference matching)."""

import sys
import types

from app.config import Settings
from app.services.embeddings import NullEmbedder, OpenAIEmbedder, build_embedder, cosine


def test_cosine_identical_orthogonal_empty():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([], [1.0]) == 0.0
    assert cosine(None, [1.0]) == 0.0


def test_null_embedder_returns_none():
    assert NullEmbedder().embed("anything") is None


def test_build_embedder_selects_by_key():
    assert isinstance(build_embedder(Settings()), NullEmbedder)
    assert isinstance(build_embedder(Settings(openai_api_key="sk-x")), OpenAIEmbedder)


def test_openai_embedder_missing_lib_returns_none():
    # langchain_openai isn't installed → ImportError → None (graceful).
    assert OpenAIEmbedder().embed("hello") is None


def test_openai_embedder_uses_lib_and_caches(monkeypatch):
    calls = {"n": 0, "clients": 0}

    mod = types.ModuleType("langchain_openai")

    class OpenAIEmbeddings:
        def __init__(self, model=None, **kwargs):
            calls["clients"] += 1  # count client constructions

        def embed_query(self, text):
            calls["n"] += 1
            return [0.1, 0.2, 0.3]

    mod.OpenAIEmbeddings = OpenAIEmbeddings
    monkeypatch.setitem(sys.modules, "langchain_openai", mod)

    emb = OpenAIEmbedder()
    assert emb.embed("") is None  # empty short-circuits
    assert emb.embed("hello") == [0.1, 0.2, 0.3]
    assert emb.embed("world") == [0.1, 0.2, 0.3]  # different text, not cached
    assert emb.embed("hello") == [0.1, 0.2, 0.3]  # cached
    assert calls["n"] == 2  # two distinct embeds, the repeat is cached
    assert calls["clients"] == 1  # client built once and reused
