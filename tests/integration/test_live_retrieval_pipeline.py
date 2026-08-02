from __future__ import annotations

import asyncio
import os

import pytest

from safemeal.bootstrap.container import AppContainer
from safemeal.evaluation.corpus import load_corpus, prepare_corpus


def test_live_embedding_milvus_rerank_pipeline() -> None:
    if os.getenv("RUN_RETRIEVAL_INTEGRATION") != "1":
        pytest.skip(
            "set RUN_RETRIEVAL_INTEGRATION=1 to run external retrieval integration"
        )

    async def scenario() -> list[dict]:
        documents = load_corpus("data/evaluation/retrieval_corpus.jsonl")
        await prepare_corpus(documents, target="milvus")
        container = AppContainer()
        try:
            service = await container.get_knowledge_service()
            return await service.search("宫保鸡丁有哪些核心食材", top_k=5)
        finally:
            await container.shutdown()

    results = asyncio.run(scenario())
    assert results
    assert any(
        item.get("metadata", {}).get("document_id") == "eval-doc-gongbao"
        or item.get("document_id") == "eval-doc-gongbao"
        for item in results
    )
    assert all("rerank_score" in item for item in results)


def test_live_milvus_returns_multiple_documents() -> None:
    if os.getenv("RUN_MULTI_DOCUMENT_INTEGRATION") != "1":
        pytest.skip(
            "set RUN_MULTI_DOCUMENT_INTEGRATION=1 after preparing the Milvus corpus"
        )

    async def scenario() -> list[dict]:
        container = AppContainer()
        try:
            knowledge = await container.get_knowledge_service()
            return await knowledge.search("比较不同食谱的食材与做法", top_k=5)
        finally:
            await container.shutdown()

    rows = asyncio.run(scenario())
    document_ids = {
        str(item.get("document_id") or item.get("metadata", {}).get("document_id"))
        for item in rows
    }
    assert len(document_ids - {"None"}) >= 2
