"""
知识服务组合辅助函数。
此模块是知识应用服务的底层架构组装点。
将具体的适配器放在这里可以防止应用层导入 Milvus、OpenAI 兼容客户端或流程设置。
"""

import asyncio

from SafeMealAgent.back.application.use_cases.knowledge.service import KnowledgeService
from SafeMealAgent.back.config.settings import settings


def create_knowledge_service() -> KnowledgeService:
    """
    构建一个配置完整的知识服务。

    该函数是同步的，因为当前的 PyMilvus SDK 执行连接和集合加载是同步的。

    异步调用者应该使用

    :func:`create_knowledge_service_async`。
    """

    from .embeddings import OpenAICompatibleEmbeddings
    from .client import VectorStore
    from .reranker import Reranker

    embedder = OpenAICompatibleEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.EMBEDDING_API_KEY,
        base_url=settings.EMBEDDING_BASE_URL,
        dimension=settings.EMBEDDING_DIMENSION,
    )
    vector_store = VectorStore(
        collection_name=settings.MILVUS_COLLECTION,
        host=settings.MILVUS_HOST,
        port=settings.MILVUS_PORT,
        dimension=settings.EMBEDDING_DIMENSION,
        index_type=settings.MILVUS_INDEX_TYPE,
        metric_type=settings.MILVUS_METRIC_TYPE,
        load_timeout_seconds=settings.MILVUS_LOAD_TIMEOUT,
    )
    return KnowledgeService(
        embedder=embedder,
        vector_store=vector_store,
        reranker=Reranker(),
        chunk_size=settings.KB_CHUNK_SIZE,
        chunk_overlap=settings.KB_CHUNK_OVERLAP,
        top_k=settings.KB_TOP_K,
        similarity_threshold=settings.KB_SIMILARITY_THRESHOLD,
        rerank_max_candidates=settings.RERANK_MAX_CANDIDATES,
        rerank_score_threshold=settings.KB_RERANK_SCORE_THRESHOLD,
        embedding_model=settings.EMBEDDING_MODEL,
        reranker_model=settings.RERANK_MODEL,
        collection_name=settings.MILVUS_COLLECTION,
        chunk_strategy=settings.KB_CHUNK_STRATEGY,
        semantic_breakpoint_threshold=settings.KB_SEMANTIC_BREAKPOINT_THRESHOLD,
        semantic_max_segments=settings.KB_SEMANTIC_MAX_SEGMENTS,
        document_chunk_strategies_json=settings.KB_DOCUMENT_CHUNK_STRATEGIES_JSON,
    )


async def create_knowledge_service_async() -> KnowledgeService:
    """Build the service outside the asyncio event-loop thread."""

    return await asyncio.to_thread(create_knowledge_service)
