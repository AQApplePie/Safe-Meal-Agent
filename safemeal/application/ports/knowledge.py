"""Knowledge retrieval ports."""

from __future__ import annotations

from typing import List, Optional, Protocol, Sequence

from safemeal.shared.types import JsonObject


class Embedder(Protocol):
    """Convert text into embedding vectors."""

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]: ...

    def embed_query(self, text: str) -> List[float]: ...


class VectorStorePort(Protocol):
    """Persistence operations required by the knowledge application service."""

    def add_documents(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: Optional[List[JsonObject]] = None,
    ) -> bool: ...

    def replace_document(
        self,
        document_id: str,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[JsonObject],
    ) -> bool:
        """Replace every stored chunk belonging to one logical document."""

        ...

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[JsonObject]: ...

    def delete_documents(self, document_ids: List[str]) -> bool:
        """Delete all chunks belonging to the supplied parent documents."""

        ...

    def get_collection_stats(self) -> JsonObject: ...

    def clear_collection(self) -> bool: ...

    def close(self) -> None: ...


class RerankerPort(Protocol):
    """Optional semantic reranking capability."""

    enabled: bool

    async def rerank(
        self,
        query: str,
        documents: List[JsonObject],
        top_k: int,
    ) -> List[JsonObject]: ...
