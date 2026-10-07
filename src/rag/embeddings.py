"""Embedding abstraction.

An ``EmbedFn`` maps texts to vectors. The default implementation uses a
local Ollama embedding model (free, no API key, CPU-friendly); tests inject
a deterministic fake.
"""

from __future__ import annotations

from typing import Callable, Protocol

from src.config import AtlasConfig


class EmbedFn(Protocol):
    def __call__(self, texts: list[str]) -> list[list[float]]: ...


def create_ollama_embedder(config: AtlasConfig) -> EmbedFn:
    from langchain_ollama import OllamaEmbeddings

    embedder = OllamaEmbeddings(
        model=config.embedding_model, base_url=config.ollama_base_url
    )

    def embed(texts: list[str]) -> list[list[float]]:
        return embedder.embed_documents(texts)

    return embed
