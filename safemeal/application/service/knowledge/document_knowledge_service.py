"""知识库用例服务。"""

import asyncio
import json
from time import perf_counter
from collections import defaultdict
from typing import cast, Optional
from uuid import uuid4

from langchain_core.documents import Document
from loguru import logger

from safemeal.application.ports import (
    DocumentEmbedder,
    DocumentReranker,
    LexicalDocumentRepository,
    VectorDocumentRepository,
)
from safemeal.application.service.knowledge.hybrid import reciprocal_rank_fusion
from safemeal.shared.types import JsonObject, to_json_object
from .chunking import (
    ChunkStrategyName,
    ChunkStrategySelector,
    RecursiveChunkStrategy,
    SemanticChunkStrategy,
)


class DocumentKnowledgeService:
    """Facade for ingesting documents and performing similarity search."""

    def __init__(
        self,
        *,
        embedder: DocumentEmbedder,
        vector_repository: VectorDocumentRepository,
        lexical_repository: LexicalDocumentRepository | None = None,
        reranker: DocumentReranker,
        chunk_size: int,
        chunk_overlap: int,
        top_k: int,
        similarity_threshold: float,
        rerank_max_candidates: int,
        embedding_model: str,
        reranker_model: str,
        collection_name: str,
        max_chunks_per_document: int = 2,
        document_recall_multiplier: int = 4,
        chunk_strategy: ChunkStrategyName = "recursive",
        semantic_breakpoint_threshold: float = 0.55,
        semantic_max_segments: int = 256,
        document_chunk_strategies_json: str = "{}",
        hybrid_enabled: bool = True,
        rrf_rank_constant: int = 60,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.default_top_k = top_k
        self.default_similarity_threshold = similarity_threshold
        self.rerank_max_candidates = rerank_max_candidates
        self.embedding_model = embedding_model
        self.reranker_model = reranker_model
        self.collection_name = collection_name
        if max_chunks_per_document < 1:
            raise ValueError("max_chunks_per_document must be positive")
        if document_recall_multiplier < 1:
            raise ValueError("document_recall_multiplier must be positive")
        self.max_chunks_per_document = max_chunks_per_document
        self.document_recall_multiplier = document_recall_multiplier
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
        self.vector_repository = vector_repository
        self.lexical_repository = lexical_repository
        self.reranker = reranker
        self.hybrid_enabled = hybrid_enabled and lexical_repository is not None
        self.rrf_rank_constant = rrf_rank_constant

        logger.info(
            "DocumentKnowledgeService initialised (chunk_size=%s, chunk_overlap=%s)",
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

    async def ingest_document(
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
        tenant_id: str = "public",
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

        # Cross-document synthesis needs enough candidates to avoid returning only
        # adjacent chunks from one long document. Reranking and document-level
        # diversity are applied after this broader recall.
        recall_k = max(top_k * self.document_recall_multiplier, top_k)
        if self.reranker.enabled:
            recall_k = max(recall_k, self.rerank_max_candidates)

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
            getattr(self.vector_repository, "host", "adapter"),
            getattr(self.vector_repository, "port", "adapter"),
            recall_k,
            filter_expr,
        )
        tenant_filter = f'tenant_id in ["public", {json.dumps(tenant_id)}]'
        resolved_filter = (
            f"({filter_expr}) and ({tenant_filter})" if filter_expr else tenant_filter
        )
        results = await asyncio.to_thread(
            self.vector_repository.search,
            embedding,
            recall_k,  # 使用更大的召回数量
            resolved_filter,
        )
        lexical_results: list[JsonObject] = []
        if self.hybrid_enabled and self.lexical_repository is not None:
            lexical_results = await asyncio.to_thread(
                self.lexical_repository.search,
                query,
                recall_k,
                {"tenant_id": tenant_id},
            )
        logger.info(
            "knowledge.milvus_search.completed collection={} result_count={} "
            "elapsed_ms={:.3f}",
            self.collection_name,
            len(results),
            (perf_counter() - vector_started) * 1000,
        )

        candidates = (
            reciprocal_rank_fusion(
                results,
                lexical_results,
                rank_constant=self.rrf_rank_constant,
            )
            if self.hybrid_enabled
            else results
        )
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
            candidates = await self.reranker.rerank(query, candidates, recall_k)
            logger.info(
                "knowledge.rerank.completed model={} result_count={} elapsed_ms={:.3f}",
                self.reranker_model,
                len(candidates),
                (perf_counter() - rerank_started) * 1000,
            )

        if (
            not self.reranker.enabled
            and not filter_by_similarity
            and similarity_threshold is not None
        ):
            candidates = [
                r for r in candidates if r.get("score", 0.0) >= similarity_threshold
            ]

        final_results = self._select_diverse_documents(candidates, top_k=top_k)
        logger.info(
            "knowledge.search.completed query={!r} result_count={} elapsed_ms={:.3f}",
            query,
            len(final_results),
            (perf_counter() - search_started) * 1000,
        )
        return final_results

    def _select_diverse_documents(
        self,
        candidates: list[JsonObject],
        *,
        top_k: int,
    ) -> list[JsonObject]:
        """Select relevant chunks while preserving cross-document coverage.

        Candidates remain ordered by vector/rerank relevance. We group them by
        their stable parent document and take one item from each group per round.
        This keeps the first pass maximally diverse, then uses additional chunks
        from the same source only when capacity remains.
        """

        groups: dict[str, list[JsonObject]] = defaultdict(list)
        order: list[str] = []
        for index, candidate in enumerate(candidates):
            metadata_value = candidate.get("metadata")
            metadata = metadata_value if isinstance(metadata_value, dict) else {}
            document_id = str(
                candidate.get("document_id")
                or metadata.get("document_id")
                or candidate.get("recipe_id")
                or metadata.get("recipe_id")
                or candidate.get("id")
                or f"unknown-{index}"
            )
            if document_id not in groups:
                order.append(document_id)
            groups[document_id].append(candidate)

        selected: list[JsonObject] = []
        for round_index in range(self.max_chunks_per_document):
            for document_id in order:
                document_candidates = groups[document_id]
                if round_index >= len(document_candidates):
                    continue
                selected.append(document_candidates[round_index])
                if len(selected) >= top_k:
                    return selected
        return selected

    async def delete_document(self, document_id: str) -> bool:
        deleted = await asyncio.to_thread(
            self.vector_repository.delete_documents, [document_id]
        )
        if self.lexical_repository is not None:
            await asyncio.to_thread(
                self.lexical_repository.delete_documents, [document_id]
            )
        return deleted

    async def get_collection_stats(self) -> JsonObject:
        def _stats() -> JsonObject:
            stats = self.vector_repository.get_collection_stats()
            stats.update(
                {
                    "chunk_size": self.chunk_size,
                    "chunk_overlap": self.chunk_overlap,
                    "chunk_strategy": self.chunk_strategy,
                    "semantic_breakpoint_threshold": self.semantic_breakpoint_threshold,
                    "semantic_max_segments": self.semantic_max_segments,
                    "document_chunk_strategies": self.document_chunk_strategies,
                    "embedding_model": self.embedding_model,
                    "max_chunks_per_document": self.max_chunks_per_document,
                    "document_recall_multiplier": self.document_recall_multiplier,
                }
            )
            return to_json_object(stats)

        return await asyncio.to_thread(_stats)

    async def clear_collection(self) -> bool:
        return await asyncio.to_thread(self.vector_repository.clear_collection)

    async def close(self) -> None:
        await asyncio.to_thread(self.vector_repository.close)
        if self.lexical_repository is not None:
            await asyncio.to_thread(self.lexical_repository.close)

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

        success = self.vector_repository.replace_document(
            document_id=document_id,
            ids=ids,
            embeddings=embeddings,
            documents=contents,
            metadatas=metadatas,
        )
        if success and self.lexical_repository is not None:
            success = self.lexical_repository.replace_document(
                document_id=document_id,
                ids=ids,
                documents=contents,
                metadatas=metadatas,
            )

        return {"add_count": len(ids) if success else 0, "ids": ids, "stored": success}
