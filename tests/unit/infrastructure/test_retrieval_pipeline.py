from __future__ import annotations

import asyncio
from typing import Sequence

from safemeal.application.use_cases.knowledge.service import KnowledgeService
from safemeal.infrastructure.retrieval.milvus.client import VectorStore
from safemeal.shared.types import JsonObject


class _Embedder:
    dimension = 2

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


class _VectorStore:
    host = "fake"
    port = 0

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[JsonObject]:
        return [{"chunk_id": "c1", "content": "宫保鸡丁包含花生", "score": 0.95}]


class _RerankerFallback:
    enabled = True

    async def rerank(
        self, query: str, documents: list[JsonObject], top_k: int
    ) -> list[JsonObject]:
        return documents[:top_k]


class _ScoredReranker:
    enabled = True

    async def rerank(
        self, query: str, documents: list[JsonObject], top_k: int
    ) -> list[JsonObject]:
        return [
            {**documents[0], "rerank_score": 0.91},
            {"chunk_id": "low", "content": "无关", "score": 0.9, "rerank_score": 0.2},
        ]


def _service(reranker: object) -> KnowledgeService:
    return KnowledgeService(
        embedder=_Embedder(),
        vector_store=_VectorStore(),  # type: ignore[arg-type]
        reranker=reranker,  # type: ignore[arg-type]
        chunk_size=100,
        chunk_overlap=10,
        top_k=5,
        similarity_threshold=0.2,
        rerank_max_candidates=20,
        embedding_model="test-embedding",
        reranker_model="test-reranker",
        collection_name="test-collection",
    )


def test_reranker_failure_fallback_preserves_vector_candidates() -> None:
    results = asyncio.run(_service(_RerankerFallback()).search("宫保鸡丁"))
    assert len(results) == 1
    assert results[0]["chunk_id"] == "c1"
    assert "rerank_score" not in results[0]


def test_successful_reranker_preserves_ranked_candidates() -> None:
    results = asyncio.run(_service(_ScoredReranker()).search("宫保鸡丁"))
    assert [item["chunk_id"] for item in results] == ["c1", "low"]
    assert results[0]["rerank_score"] == 0.91


def test_milvus_delete_is_a_noop_for_a_new_empty_collection() -> None:
    class EmptyCollection:
        num_entities = 0
        delete_called = False

        def delete(self, expression: str, timeout: float) -> None:
            self.delete_called = True

    collection = EmptyCollection()
    store = VectorStore.__new__(VectorStore)
    store.collection = collection
    store.collection_name = "empty-test"
    store.load_timeout_seconds = 1
    store._closed = False

    assert store.delete_documents(["eval-doc"]) is True
    assert not collection.delete_called


def test_search_diversifies_chunks_across_documents() -> None:
    class MultiDocumentStore(_VectorStore):
        def search(
            self,
            query_embedding: list[float],
            top_k: int = 10,
            filter_expr: str | None = None,
        ) -> list[JsonObject]:
            return [
                {
                    "id": "a-1",
                    "content": "A1",
                    "score": 0.99,
                    "metadata": {"document_id": "a"},
                },
                {
                    "id": "a-2",
                    "content": "A2",
                    "score": 0.98,
                    "metadata": {"document_id": "a"},
                },
                {
                    "id": "a-3",
                    "content": "A3",
                    "score": 0.97,
                    "metadata": {"document_id": "a"},
                },
                {
                    "id": "b-1",
                    "content": "B1",
                    "score": 0.96,
                    "metadata": {"document_id": "b"},
                },
                {
                    "id": "c-1",
                    "content": "C1",
                    "score": 0.95,
                    "metadata": {"document_id": "c"},
                },
            ]

    service = _service(_RerankerFallback())
    service.vector_store = MultiDocumentStore()  # type: ignore[assignment]
    results = asyncio.run(service.search("跨文档归纳", top_k=4))

    assert [item["id"] for item in results] == ["a-1", "b-1", "c-1", "a-2"]
    assert len({item["metadata"]["document_id"] for item in results[:3]}) == 3
