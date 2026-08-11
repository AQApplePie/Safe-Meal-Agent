"""Document embedding boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class DocumentEmbedder(Protocol):
    """Convert knowledge documents and queries into embedding vectors."""

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


__all__ = ["DocumentEmbedder"]
