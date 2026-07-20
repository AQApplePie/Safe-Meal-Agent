from __future__ import annotations

import asyncio
from typing import Sequence

from SafeMealAgent.back.application.use_cases.knowledge.service import KnowledgeService
from SafeMealAgent.back.infrastructure.retrieval.milvus.client import VectorStore
from SafeMealAgent.back.infrastructure.retrieval.lightrag.service import LightRAGService
from lightrag.base import DocProcessingStatus, DocStatus
from SafeMealAgent.back.shared.types import JsonObject


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
        rerank_score_threshold=0.8,
        embedding_model="test-embedding",
        reranker_model="test-reranker",
        collection_name="test-collection",
    )


def test_reranker_failure_fallback_preserves_vector_candidates() -> None:
    results = asyncio.run(_service(_RerankerFallback()).search("宫保鸡丁"))
    assert len(results) == 1
    assert results[0]["chunk_id"] == "c1"
    assert "rerank_score" not in results[0]


def test_successful_reranker_still_applies_score_threshold() -> None:
    results = asyncio.run(_service(_ScoredReranker()).search("宫保鸡丁"))
    assert [item["chunk_id"] for item in results] == ["c1"]
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


def test_lightrag_insert_reports_pipeline_failure_instead_of_false_success() -> None:
    class FailedRag:
        async def aget_docs_by_ids(self, document_id: str):
            return {}

        async def ainsert(self, document: str) -> str:
            return "track-1"

        async def aget_docs_by_track_id(
            self, track_id: str
        ) -> dict[str, DocProcessingStatus]:
            return {
                "doc-1": DocProcessingStatus(
                    content_summary="failed document",
                    content_length=15,
                    file_path="unknown_source",
                    status=DocStatus.FAILED,
                    created_at="2026-07-15T00:00:00Z",
                    updated_at="2026-07-15T00:00:00Z",
                    track_id=track_id,
                    error_msg="entity extraction failed",
                    metadata={},
                )
            }

    service = LightRAGService(working_dir="unused")
    service.rag = FailedRag()  # type: ignore[assignment]
    service.initialized = True

    result = asyncio.run(service.insert_documents(["document"]))

    assert result.success == 0
    assert result.failed == 1
    assert "entity extraction failed" in result.errors[0]


def test_lightrag_insert_treats_verified_processed_duplicate_as_idempotent() -> None:
    class DuplicateRag:
        async def aget_docs_by_ids(self, document_id: str):
            return {
                document_id: {
                    "status": "processed",
                    "content_summary": "existing document",
                }
            }

        async def ainsert(self, document: str) -> str:
            raise RuntimeError(
                "File name already exists. Original doc_id: doc-existing, Status: processed"
            )

    service = LightRAGService(working_dir="unused")
    service.rag = DuplicateRag()  # type: ignore[assignment]
    service.initialized = True

    result = asyncio.run(service.insert_documents(["document"]))

    assert result.success == 1
    assert result.already_present == 1
    assert result.failed == 0
