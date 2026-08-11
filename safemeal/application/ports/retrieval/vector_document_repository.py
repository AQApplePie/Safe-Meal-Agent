"""Vector-document persistence boundary."""

from __future__ import annotations

from typing import Protocol

from safemeal.shared.types import JsonObject


class VectorDocumentRepository(Protocol):
    """Persist and query chunked knowledge documents by embedding vector."""

    def add_documents(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[JsonObject] | None = None,
    ) -> bool: ...

    def replace_document(
        self,
        document_id: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[JsonObject],
    ) -> bool: ...

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[JsonObject]: ...

    def delete_documents(self, document_ids: list[str]) -> bool: ...

    def get_collection_stats(self) -> JsonObject: ...

    def clear_collection(self) -> bool: ...

    def close(self) -> None: ...


__all__ = ["VectorDocumentRepository"]
