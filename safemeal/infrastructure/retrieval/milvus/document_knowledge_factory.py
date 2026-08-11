"""Build document knowledge services with Milvus-backed adapters."""

import asyncio

from safemeal.application.use_cases.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.config.settings import settings


def create_document_knowledge_service() -> DocumentKnowledgeService:
    """
    构建一个配置完整的知识服务。

    该函数是同步的，因为当前的 PyMilvus SDK 执行连接和集合加载是同步的。

    异步调用者应该使用

    :func:`create_document_knowledge_service_async`。
    """

    from .document_embedder import OpenAICompatibleDocumentEmbedder
    from .document_reranker import HttpDocumentReranker
    from .vector_document_repository import MilvusVectorDocumentRepository

    embedder = OpenAICompatibleDocumentEmbedder(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.EMBEDDING_API_KEY,
        base_url=settings.EMBEDDING_BASE_URL,
        dimension=settings.EMBEDDING_DIMENSION,
    )
    vector_repository = MilvusVectorDocumentRepository(
        collection_name=settings.MILVUS_COLLECTION,
        host=settings.MILVUS_HOST,
        port=settings.MILVUS_PORT,
        dimension=settings.EMBEDDING_DIMENSION,
        index_type=settings.MILVUS_INDEX_TYPE,
        metric_type=settings.MILVUS_METRIC_TYPE,
        load_timeout_seconds=settings.MILVUS_LOAD_TIMEOUT,
    )
    return DocumentKnowledgeService(
        embedder=embedder,
        vector_repository=vector_repository,
        reranker=HttpDocumentReranker(),
        chunk_size=settings.KB_CHUNK_SIZE,
        chunk_overlap=settings.KB_CHUNK_OVERLAP,
        top_k=settings.KB_TOP_K,
        similarity_threshold=settings.KB_SIMILARITY_THRESHOLD,
        rerank_max_candidates=settings.RERANK_MAX_CANDIDATES,
        embedding_model=settings.EMBEDDING_MODEL,
        reranker_model=settings.RERANK_MODEL,
        collection_name=settings.MILVUS_COLLECTION,
        max_chunks_per_document=settings.KB_MAX_CHUNKS_PER_DOCUMENT,
        document_recall_multiplier=settings.KB_DOCUMENT_RECALL_MULTIPLIER,
        chunk_strategy=settings.KB_CHUNK_STRATEGY,
        semantic_breakpoint_threshold=settings.KB_SEMANTIC_BREAKPOINT_THRESHOLD,
        semantic_max_segments=settings.KB_SEMANTIC_MAX_SEGMENTS,
        document_chunk_strategies_json=settings.KB_DOCUMENT_CHUNK_STRATEGIES_JSON,
    )


async def create_document_knowledge_service_async() -> DocumentKnowledgeService:
    """Build the service outside the asyncio event-loop thread."""

    return await asyncio.to_thread(create_document_knowledge_service)
