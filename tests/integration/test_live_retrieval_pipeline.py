from __future__ import annotations

import asyncio
import os

import pytest

from SafeMealAgent.back.bootstrap.container import AppContainer
from SafeMealAgent.back.application.agents.models import Observation
from SafeMealAgent.back.application.agents.retrieval_fusion import fuse_retrieval_observations
from SafeMealAgent.back.evaluation.corpus import load_corpus, prepare_corpus


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


def test_live_milvus_lightrag_fusion_pipeline() -> None:
    if os.getenv("RUN_MULTI_ROUTE_INTEGRATION") != "1":
        pytest.skip(
            "set RUN_MULTI_ROUTE_INTEGRATION=1 after preparing both retrieval indexes"
        )

    async def scenario() -> tuple[list[dict], str]:
        container = AppContainer()
        try:
            knowledge = await container.get_knowledge_service()
            milvus = await knowledge.search("宫保鸡丁的核心食材和所属菜系", top_k=5)
            lightrag_result = await container.get_lightrag_service().query(
                "结合文档关系说明宫保鸡丁的核心食材和所属菜系",
                mode="hybrid",
                top_k=5,
            )
            return milvus, str(lightrag_result)
        finally:
            await container.shutdown()

    milvus_rows, lightrag_response = asyncio.run(scenario())
    fused = fuse_retrieval_observations(
        [
            Observation(
                call_id="live-milvus",
                tool_name="milvus_vector_search",
                purpose="原文证据",
                success_criteria="命中评测文档",
                ok=bool(milvus_rows),
                status="ok" if milvus_rows else "unavailable",
                has_data=bool(milvus_rows),
                summary="live Milvus result",
                data={"documents": milvus_rows},
            ),
            Observation(
                call_id="live-lightrag",
                tool_name="lightrag_search",
                purpose="跨文档关系",
                success_criteria="生成关系证据",
                ok=bool(lightrag_response.strip()),
                status="ok" if lightrag_response.strip() else "unavailable",
                has_data=bool(lightrag_response.strip()),
                summary="live LightRAG result",
                data={"response": lightrag_response},
            ),
        ]
    )

    assert milvus_rows
    assert "宫保鸡丁" in lightrag_response
    assert fused is not None and fused.ok
    assert set(fused.data["successful_routes"]) == {
        "milvus_vector_search",
        "lightrag_search",
    }
    assert fused.data["degraded_routes"] == []
    assert fused.data["count"] >= 2
