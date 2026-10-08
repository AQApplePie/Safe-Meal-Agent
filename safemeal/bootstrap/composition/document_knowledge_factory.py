"""装配文档知识摄取与检索服务。"""

import asyncio

from safemeal.modules.knowledge.application.knowledge.document_knowledge_service import (
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

    from safemeal.infrastructure.retrieval.milvus.document_embedder import (
        OpenAICompatibleDocumentEmbedder,
    )
    from safemeal.infrastructure.retrieval.milvus.document_reranker import (
        HttpDocumentReranker,
    )
    from safemeal.infrastructure.retrieval.milvus.vector_document_repository import (
        MilvusVectorDocumentRepository,
    )
    from safemeal.infrastructure.retrieval.sqlite_bm25 import SqliteBm25Repository

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
        lexical_repository=(
            SqliteBm25Repository(settings.KB_BM25_PATH)
            if settings.KB_HYBRID_ENABLED
            else None
        ),
        reranker=HttpDocumentReranker(
            enabled=settings.RERANK_ENABLED,
            provider=settings.RERANK_PROVIDER,
            base_url=settings.RERANK_BASE_URL,
            endpoint=settings.RERANK_ENDPOINT,
            model=settings.RERANK_MODEL,
            api_key=settings.RERANK_API_KEY,
            top_n=settings.RERANK_TOP_N,
            timeout=settings.RERANK_TIMEOUT,
        ),
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
        hybrid_enabled=settings.KB_HYBRID_ENABLED,
        rrf_rank_constant=settings.KB_RRF_RANK_CONSTANT,
    )


async def create_document_knowledge_service_async() -> DocumentKnowledgeService:

    return await asyncio.to_thread(create_document_knowledge_service)
