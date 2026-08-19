from __future__ import annotations

import pytest

from safemeal.application.use_cases.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)


class Embedder:
    dimension = 2

    def embed_query(self, query: str) -> list[float]:
        return [1.0, 0.0]

    def embed_documents(self, documents: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in documents]


class VectorRepo:
    def search(self, *_args):
        return [
            {
                "id": "semantic",
                "document_id": "d2",
                "content": "相似语义",
                "score": 0.99,
            },
            {
                "id": "exact",
                "document_id": "d1",
                "content": "花生过敏原",
                "score": 0.55,
            },
        ]

    def replace_document(self, **_kwargs):
        return True

    def delete_documents(self, _ids):
        return True

    def get_collection_stats(self):
        return {}

    def clear_collection(self):
        return True

    def close(self):
        return None


class LexicalRepo:
    def search(self, query: str, top_k: int, filter_by=None):
        assert query == "花生过敏原"
        return [
            {"id": "exact", "document_id": "d1", "content": "花生过敏原", "score": 9.0}
        ]

    def replace_document(self, **_kwargs):
        return True

    def delete_documents(self, _ids):
        return True

    def close(self):
        return None


class Reranker:
    enabled = False

    async def rerank(self, query, candidates, top_k):
        return candidates[:top_k]


@pytest.mark.rag
async def test_exact_and_semantic_evidence_are_fused() -> None:
    service = DocumentKnowledgeService(
        embedder=Embedder(),
        vector_repository=VectorRepo(),
        lexical_repository=LexicalRepo(),
        reranker=Reranker(),
        chunk_size=128,
        chunk_overlap=16,
        top_k=2,
        similarity_threshold=0,
        rerank_max_candidates=10,
        embedding_model="fake",
        reranker_model="fake",
        collection_name="test",
        hybrid_enabled=True,
        rrf_rank_constant=1,
    )

    results = await service.search("花生过敏原", top_k=2)

    assert results[0]["id"] == "exact"
    assert results[0]["retrieval_channels"] == ["vector", "bm25"]
