"""知识库用例服务。"""

import asyncio
import json
from time import perf_counter
from typing import cast, Optional
from uuid import uuid4

from langchain_core.documents import Document
from loguru import logger

from SafeMealAgent.back.application.ports import Embedder, RerankerPort, VectorStorePort
from SafeMealAgent.back.shared.types import JsonObject, to_json_object
from .chunking import (
    ChunkStrategyName,
    ChunkStrategySelector,
    RecursiveChunkStrategy,
    SemanticChunkStrategy,
)


class KnowledgeService:
    """Facade for ingesting documents and performing similarity search."""

    def __init__(
        self,
        *,
        embedder: Embedder,
        vector_store: VectorStorePort,
        reranker: RerankerPort,
        chunk_size: int,
        chunk_overlap: int,
        top_k: int,
        similarity_threshold: float,
        rerank_max_candidates: int,
        rerank_score_threshold: float,
        embedding_model: str,
        reranker_model: str,
        collection_name: str,
        chunk_strategy: ChunkStrategyName = "recursive",
        semantic_breakpoint_threshold: float = 0.55,
        semantic_max_segments: int = 256,
        document_chunk_strategies_json: str = "{}",
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.default_top_k = top_k
        self.default_similarity_threshold = similarity_threshold
        self.rerank_max_candidates = rerank_max_candidates
        self.rerank_score_threshold = rerank_score_threshold
        self.embedding_model = embedding_model
        self.reranker_model = reranker_model
        self.collection_name = collection_name
        self.chunk_strategy = chunk_strategy
        self.semantic_breakpoint_threshold = semantic_breakpoint_threshold
        self.semantic_max_segments = semantic_max_segments
        raw_document_strategies = json.loads(document_chunk_strategies_json)
        if not isinstance(raw_document_strategies, dict):
            raise ValueError("document chunk strategies must be a JSON object")
        document_strategies: dict[str, ChunkStrategyName] = {}
        for key, value in raw_document_strategies.items():
            if value not in {"auto", "recursive", "semantic"}:
                raise ValueError(f"unsupported chunk strategy for {key}: {value}")
            document_strategies[str(key).casefold()] = cast(ChunkStrategyName, value)
        self.document_chunk_strategies = document_strategies
        recursive = RecursiveChunkStrategy(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        semantic = SemanticChunkStrategy(
            embedder=embedder,
            recursive=recursive,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            breakpoint_threshold=semantic_breakpoint_threshold,
            max_segments=semantic_max_segments,
        )
        self.chunk_selector = ChunkStrategySelector(
            default_strategy=chunk_strategy,
            document_strategies=document_strategies,
            recursive=recursive,
            semantic=semantic,
        )

        self.embedder = embedder
        self.vector_store = vector_store
        self.reranker = reranker

        logger.info(
            "KnowledgeService initialised (chunk_size=%s, chunk_overlap=%s)",
            self.chunk_size,
            self.chunk_overlap,
        )

    async def ingest_text(
        self,
        text: str,
        *,
        metadata: Optional[JsonObject] = None,
        chunk_strategy: ChunkStrategyName | None = None,
    ) -> JsonObject:
        if not text or not text.strip():
            return {"add_count": 0, "ids": []}

        resolved_metadata = dict(metadata or {})
        document_id = str(resolved_metadata.get("document_id") or uuid4().hex).strip()
        if not document_id:
            raise ValueError("document_id cannot be blank")
        resolved_metadata["document_id"] = document_id

        requested_strategy = chunk_strategy or cast(
            ChunkStrategyName,
            resolved_metadata.pop("chunk_strategy", self.chunk_strategy),
        )
        if requested_strategy not in {"auto", "recursive", "semantic"}:
            raise ValueError(f"unsupported chunk strategy: {requested_strategy}")
        selected_strategy, documents = await asyncio.to_thread(
            self._split_into_documents,
            text,
            resolved_metadata,
            requested_strategy,
        )
        if not documents:
            return {"add_count": 0, "ids": []}

        embeddings = await asyncio.to_thread(
            self.embedder.embed_documents,
            [doc.page_content for doc in documents],
        )

        result = await asyncio.to_thread(
            self._replace_document,
            document_id,
            documents,
            embeddings,
        )
        result["chunk_strategy"] = selected_strategy
        return result

    async def add_document(
        self,
        *,
        doc_id: Optional[str],
        title: str,
        content: str,
        metadata: Optional[JsonObject] = None,
    ) -> bool:
        meta = metadata.copy() if metadata else {}
        meta.setdefault("title", title)
        meta.setdefault("name", title)
        if doc_id:
            meta.setdefault("document_id", doc_id)
        result = await self.ingest_text(content, metadata=meta)
        return result.get("add_count", 0) > 0

    async def search(
        self,
        query: str,
        *,
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
        filter_expr: Optional[str] = None,
        filter_by_similarity: bool = True,
    ) -> list[JsonObject]:
        if not query or not query.strip():
            return []

        search_started = perf_counter()
        top_k = top_k or self.default_top_k
        similarity_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self.default_similarity_threshold
        )

        # 如果启用 reranker，先召回更多候选文档
        recall_k = top_k
        if self.reranker.enabled:
            recall_k = self.rerank_max_candidates

        logger.info(
            "knowledge.search.start query={!r} top_k={} recall_k={} "
            "filter_expr={} reranker_enabled={}",
            query,
            top_k,
            recall_k,
            filter_expr,
            self.reranker.enabled,
        )
        embedding_started = perf_counter()
        logger.info(
            "knowledge.embedding.start model={} expected_dimension={}",
            self.embedding_model,
            getattr(self.embedder, "dimension", "unknown"),
        )
        try:
            embedding = await asyncio.to_thread(self.embedder.embed_query, query)
        except Exception:
            logger.exception(
                "knowledge.embedding.failed model={} elapsed_ms={:.3f}",
                self.embedding_model,
                (perf_counter() - embedding_started) * 1000,
            )
            raise
        logger.info(
            "knowledge.embedding.completed model={} actual_dimension={} "
            "elapsed_ms={:.3f}",
            self.embedding_model,
            len(embedding),
            (perf_counter() - embedding_started) * 1000,
        )

        vector_started = perf_counter()
        logger.info(
            "knowledge.milvus_search.start collection={} host={} port={} "
            "recall_k={} filter_expr={}",
            self.collection_name,
            getattr(self.vector_store, "host", "adapter"),
            getattr(self.vector_store, "port", "adapter"),
            recall_k,
            filter_expr,
        )
        results = await asyncio.to_thread(
            self.vector_store.search,
            embedding,
            recall_k,  # 使用更大的召回数量
            filter_expr,
        )
        logger.info(
            "knowledge.milvus_search.completed collection={} result_count={} "
            "elapsed_ms={:.3f}",
            self.collection_name,
            len(results),
            (perf_counter() - vector_started) * 1000,
        )

        candidates = results
        if filter_by_similarity and similarity_threshold is not None:
            candidates = [
                r for r in candidates if r.get("score", 0.0) >= similarity_threshold
            ]

        # 使用 reranker 精排
        if candidates and self.reranker.enabled:
            rerank_started = perf_counter()
            logger.info(
                "knowledge.rerank.start model={} candidate_count={} top_k={}",
                self.reranker_model,
                len(candidates),
                top_k,
            )
            candidates = await self.reranker.rerank(query, candidates, top_k)
            logger.info(
                "knowledge.rerank.completed model={} result_count={} "
                "elapsed_ms={:.3f}",
                self.reranker_model,
                len(candidates),
                (perf_counter() - rerank_started) * 1000,
            )

        if self.reranker.enabled:
            # A reranker transport failure deliberately returns the original
            # vector candidates. Those rows have no rerank_score and must remain
            # usable; filtering a missing score as 0 would turn a graceful
            # fallback into an empty result set.
            scored_candidates = [r for r in candidates if "rerank_score" in r]
            if scored_candidates:
                candidates = [
                    r
                    for r in scored_candidates
                    if r.get("rerank_score", 0.0) >= self.rerank_score_threshold
                ]
            else:
                logger.warning(
                    "knowledge.rerank.fallback reason=no_rerank_scores "
                    "preserved_candidates={}",
                    len(candidates),
                )
        elif not filter_by_similarity and similarity_threshold is not None:
            candidates = [
                r for r in candidates if r.get("score", 0.0) >= similarity_threshold
            ]

        final_results = candidates[:top_k]
        logger.info(
            "knowledge.search.completed query={!r} result_count={} elapsed_ms={:.3f}",
            query,
            len(final_results),
            (perf_counter() - search_started) * 1000,
        )
        return final_results

    async def delete_document(self, document_id: str) -> bool:
        return await asyncio.to_thread(
            self.vector_store.delete_documents, [document_id]
        )

    async def get_stats(self) -> JsonObject:
        def _stats() -> JsonObject:
            stats = self.vector_store.get_collection_stats()
            stats.update(
                {
                    "chunk_size": self.chunk_size,
                    "chunk_overlap": self.chunk_overlap,
                    "chunk_strategy": self.chunk_strategy,
                    "semantic_breakpoint_threshold": self.semantic_breakpoint_threshold,
                    "semantic_max_segments": self.semantic_max_segments,
                    "document_chunk_strategies": self.document_chunk_strategies,
                    "embedding_model": self.embedding_model,
                }
            )
            return to_json_object(stats)

        return await asyncio.to_thread(_stats)

    async def clear(self) -> bool:
        return await asyncio.to_thread(self.vector_store.clear_collection)

    async def close(self) -> None:
        await asyncio.to_thread(self.vector_store.close)

    def _split_into_documents(
        self,
        text: str,
        metadata: JsonObject,
        requested_strategy: ChunkStrategyName,
    ) -> tuple[str, list[Document]]:
        return self.chunk_selector.split(text, metadata, requested_strategy)

    def _replace_document(
        self,
        document_id: str,
        documents: list[Document],
        embeddings: list[list[float]],
    ) -> JsonObject:
        if not documents or not embeddings:
            return {"add_count": 0, "ids": [], "stored": False}
        if len(documents) != len(embeddings):
            raise ValueError(
                "embedding provider returned a different number of vectors than documents"
            )

        ids: list[str] = []
        contents: list[str] = []
        metadatas: list[JsonObject] = []

        for index, doc in enumerate(documents):
            metadata = to_json_object(doc.metadata or {})
            base_id_value = (
                metadata.get("document_id")
                or metadata.get("id")
                or metadata.get("source")
                or uuid4().hex
            )
            base_id = str(base_id_value).strip()
            if not base_id:
                raise ValueError("document_id cannot be blank")
            chunk_id = f"{base_id}_{index}"
            metadata["document_id"] = base_id
            metadata.setdefault("chunk_id", chunk_id)
            metadata.setdefault(
                "name", metadata.get("name") or metadata.get("title") or ""
            )

            ids.append(chunk_id)
            contents.append(doc.page_content)
            metadatas.append(metadata)

        success = self.vector_store.replace_document(
            document_id=document_id,
            ids=ids,
            embeddings=embeddings,
            documents=contents,
            metadatas=metadatas,
        )

        return {"add_count": len(ids) if success else 0, "ids": ids, "stored": success}
