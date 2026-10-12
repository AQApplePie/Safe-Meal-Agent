"""知识库用例服务。"""

import asyncio
import json
from time import perf_counter
from collections import defaultdict
from typing import cast, Optional
from uuid import uuid4

from langchain_core.documents import Document
from loguru import logger

from safemeal.modules.knowledge.ports.retrieval import (
    DocumentEmbedder,
    DocumentReranker,
    LexicalDocumentRepository,
    VectorDocumentRepository,
)
from safemeal.modules.knowledge.application.knowledge.hybrid import (
    reciprocal_rank_fusion,
)
from safemeal.shared.types import JsonObject, to_json_object
from .chunking import (
    ChunkStrategyName,
    ChunkStrategySelector,
    RecursiveChunkStrategy,
    SemanticChunkStrategy,
)


# 类说明（业务或基础设施实现类）：DocumentKnowledgeService
# 作用：实现文档摄取与混合检索服务，封装该组件的业务处理与依赖协作。
class DocumentKnowledgeService:
    # 方法说明：__init__
    # 作用：初始化文档摄取与混合检索服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   embedder（DocumentEmbedder）：将文本转换成向量的嵌入组件。
    #   vector_repository（VectorDocumentRepository）：文档向量存储与检索仓储。
    #   lexical_repository（LexicalDocumentRepository | None）：文档词法检索仓储；默认值为
    # None。
    #   reranker（DocumentReranker）：文档片段重排组件。
    #   chunk_size（int）：文档分块的目标字符数。
    #   chunk_overlap（int）：相邻文档片段的重叠字符数。
    #   top_k（int）：检索返回的最大候选数。
    #   similarity_threshold（float）：向量检索候选的最低相似度。
    #   rerank_max_candidates（int）：最多送入重排的候选片段数。
    #   embedding_model（str）：文本嵌入模型名称。
    #   reranker_model（str）：重排模型名称。
    #   collection_name（str）：向量集合名称。
    #   max_chunks_per_document（int）：单文档最多生成的片段数；默认值为 2。
    #   document_recall_multiplier（int）：片段召回相对于最终文档数的扩大倍数；默认值为 4。
    #   chunk_strategy（ChunkStrategyName）：请求使用的文档分块策略；默认值为 'recursive'。
    #   semantic_breakpoint_threshold（float）：语义分块的边界相似度阈值；默认值为 0.55。
    #   semantic_max_segments（int）：单次语义分块最多处理的基础句段数；默认值为 256。
    #   document_chunk_strategies_json（str）：按文档配置分块策略的 JSON 文本；默认值为 '{}'。
    #   hybrid_enabled（bool）：是否启用向量与词法混合检索；默认值为 True。
    #   rrf_rank_constant（int）：RRF 排名融合的平滑常数；默认值为 60。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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
        # 实例属性说明：chunk_size
        # 作用：文档分块的目标字符数。
        self.chunk_size = chunk_size
        # 实例属性说明：chunk_overlap
        # 作用：相邻文档片段的重叠字符数。
        self.chunk_overlap = chunk_overlap
        # 实例属性说明：default_top_k
        # 作用：检索返回的最大候选数。
        self.default_top_k = top_k
        # 实例属性说明：default_similarity_threshold
        # 作用：向量检索候选的最低相似度。
        self.default_similarity_threshold = similarity_threshold
        # 实例属性说明：rerank_max_candidates
        # 作用：最多送入重排的候选片段数。
        self.rerank_max_candidates = rerank_max_candidates
        # 实例属性说明：embedding_model
        # 作用：文本嵌入模型名称。
        self.embedding_model = embedding_model
        # 实例属性说明：reranker_model
        # 作用：重排模型名称。
        self.reranker_model = reranker_model
        # 实例属性说明：collection_name
        # 作用：向量集合名称。
        self.collection_name = collection_name
        if max_chunks_per_document < 1:
            raise ValueError("max_chunks_per_document must be positive")
        if document_recall_multiplier < 1:
            raise ValueError("document_recall_multiplier must be positive")
        # 实例属性说明：max_chunks_per_document
        # 作用：单文档最多生成的片段数。
        self.max_chunks_per_document = max_chunks_per_document
        # 实例属性说明：document_recall_multiplier
        # 作用：片段召回相对于最终文档数的扩大倍数。
        self.document_recall_multiplier = document_recall_multiplier
        # 实例属性说明：chunk_strategy
        # 作用：请求使用的文档分块策略。
        self.chunk_strategy = chunk_strategy
        # 实例属性说明：semantic_breakpoint_threshold
        # 作用：语义分块的边界相似度阈值。
        self.semantic_breakpoint_threshold = semantic_breakpoint_threshold
        # 实例属性说明：semantic_max_segments
        # 作用：单次语义分块最多处理的基础句段数。
        self.semantic_max_segments = semantic_max_segments
        raw_document_strategies = json.loads(document_chunk_strategies_json)
        if not isinstance(raw_document_strategies, dict):
            raise ValueError("document chunk strategies must be a JSON object")
        document_strategies: dict[str, ChunkStrategyName] = {}
        for key, value in raw_document_strategies.items():
            if value not in {"auto", "recursive", "semantic"}:
                raise ValueError(f"unsupported chunk strategy for {key}: {value}")
            document_strategies[str(key).casefold()] = cast(ChunkStrategyName, value)
        # 实例属性说明：document_chunk_strategies
        # 作用：按文档类型指定的切分策略，覆盖通用默认策略。
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
        # 实例属性说明：chunk_selector
        # 作用：依据文档类型与默认策略选择切分实现的组件。
        self.chunk_selector = ChunkStrategySelector(
            default_strategy=chunk_strategy,
            document_strategies=document_strategies,
            recursive=recursive,
            semantic=semantic,
        )

        # 实例属性说明：embedder
        # 作用：将文本转换成向量的嵌入组件。
        self.embedder = embedder
        # 实例属性说明：vector_repository
        # 作用：文档向量存储与检索仓储。
        self.vector_repository = vector_repository
        # 实例属性说明：lexical_repository
        # 作用：文档词法检索仓储。
        self.lexical_repository = lexical_repository
        # 实例属性说明：reranker
        # 作用：文档片段重排组件。
        self.reranker = reranker
        # 实例属性说明：hybrid_enabled
        # 作用：是否启用向量与词法混合检索。
        self.hybrid_enabled = hybrid_enabled and lexical_repository is not None
        # 实例属性说明：rrf_rank_constant
        # 作用：RRF 排名融合的平滑常数。
        self.rrf_rank_constant = rrf_rank_constant

        logger.info(
            "DocumentKnowledgeService initialised (chunk_size=%s, chunk_overlap=%s)",
            self.chunk_size,
            self.chunk_overlap,
        )

    # 方法说明：ingest_text
    # 作用：切分文本并生成向量及词法索引记录。
    # 入参：
    #   text（str）：待解析、检索、切分或渲染的文本。
    #   metadata（Optional[JsonObject]）：文档、消息或证据的来源与辅助元数据；默认值为 None。
    #   chunk_strategy（ChunkStrategyName | None）：请求使用的文档分块策略；默认值为 None。
    # 出参：JsonObject；JSON 字段映射。
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

    # 方法说明：ingest_document
    # 作用：解析上传文档并写入知识检索存储，更新摄取状态。
    # 入参：
    #   doc_id（Optional[str]）：文档标识。
    #   title（str）：会话、文档或菜谱标题。
    #   content（str）：当前文件、消息或证据的正文内容。
    #   metadata（Optional[JsonObject]）：文档、消息或证据的来源与辅助元数据；默认值为 None。
    # 出参：bool；对应存储更新或删除是否完成。
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

    # 方法说明：search
    # 作用：通过文档摄取与混合检索服务按查询条件检索候选及其证据。
    # 入参：
    #   query（str）：结构化查询条件或检索问题。
    #   top_k（Optional[int]）：检索返回的最大候选数；默认值为 None。
    #   similarity_threshold（Optional[float]）：向量检索候选的最低相似度；默认值为 None。
    #   filter_expr（Optional[str]）：当前检索使用的过滤条件或表达式；默认值为 None。
    #   filter_by_similarity（bool）：是否启用向量相似度阈值过滤；默认值为 True。
    #   tenant_id（str）：可信租户标识，用于业务数据隔离；默认值为 'public'。
    # 出参：list[JsonObject]；JSON 字段映射的集合。
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
        top_k = self.default_top_k if top_k is None else top_k
        if top_k < 1:
            raise ValueError("top_k must be positive")
        similarity_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self.default_similarity_threshold
        )

        recall_k = max(top_k * self.document_recall_multiplier, top_k)
        if self.reranker.enabled:
            recall_k = max(recall_k, self.rerank_max_candidates)

        logger.info(
            "knowledge.search.start query_chars={} top_k={} recall_k={} "
            "filter_expr={} reranker_enabled={}",
            len(query),
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
        if (
            self.hybrid_enabled
            and self.lexical_repository is not None
            and not filter_expr
        ):
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

        # Similarity thresholds belong only to the vector channel; BM25 and RRF
        # scores have different scales. Explicit vector filters disable lexical
        # recall because a Milvus expression cannot safely be interpreted by FTS.
        # 方法说明：permitted
        # 作用：判断当前预算与状态是否允许继续执行动作。
        # 入参：
        #   row（JsonObject）：当前 SQL 查询结果行。
        # 出参：bool；当前状态与预算是否允许该动作。
        def permitted(row: JsonObject) -> bool:
            metadata = row.get("metadata")
            owner = (
                metadata.get("tenant_id", "public")
                if isinstance(metadata, dict)
                else "public"
            )
            return owner in {"public", tenant_id}

        results = [row for row in results if permitted(row)]
        lexical_results = [row for row in lexical_results if permitted(row)]
        if filter_by_similarity and similarity_threshold is not None:
            results = [
                row for row in results if row.get("score", 0.0) >= similarity_threshold
            ]
        candidates = (
            reciprocal_rank_fusion(
                results, lexical_results, rank_constant=self.rrf_rank_constant
            )
            if self.hybrid_enabled and not filter_expr
            else results
        )
        if self.reranker.enabled:
            candidates = candidates[: max(top_k, self.rerank_max_candidates)]
        allowed = {str(row.get("id")): row for row in candidates if row.get("id")}
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

        # A reranker may reorder retrieved chunks, never introduce new evidence.
        if self.reranker.enabled:
            validated: list[JsonObject] = []
            seen: set[str] = set()
            for row in candidates:
                key = str(row.get("id"))
                if key in allowed and key not in seen:
                    original = dict(allowed[key])
                    if "rerank_score" in row:
                        original["rerank_score"] = row["rerank_score"]
                    validated.append(original)
                    seen.add(key)
            candidates = validated

        final_results = self._select_diverse_documents(candidates, top_k=top_k)
        logger.info(
            "knowledge.search.completed query_chars={} result_count={} elapsed_ms={:.3f}",
            len(query),
            len(final_results),
            (perf_counter() - search_started) * 1000,
        )
        return final_results

    # 方法说明：_select_diverse_documents
    # 作用：在候选片段中控制同文档占比，保留来源多样性。
    # 入参：
    #   candidates（list[JsonObject]）：待筛选或待排序的候选集合。
    #   top_k（int）：检索返回的最大候选数。
    # 出参：list[JsonObject]；JSON 字段映射的集合。
    def _select_diverse_documents(
        self,
        candidates: list[JsonObject],
        *,
        top_k: int,
    ) -> list[JsonObject]:

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

    # 方法说明：delete_document
    # 作用：删除当前权限范围内文档的检索记录。
    # 入参：
    #   document_id（str）：文档标识。
    # 出参：bool；对应存储更新或删除是否完成。
    async def delete_document(self, document_id: str) -> bool:
        deleted = await asyncio.to_thread(
            self.vector_repository.delete_documents, [document_id]
        )
        if self.lexical_repository is not None:
            lexical_deleted = await asyncio.to_thread(
                self.lexical_repository.delete_documents, [document_id]
            )
            deleted = deleted and lexical_deleted
        return deleted

    # 方法说明：get_collection_stats
    # 作用：查询知识检索集合的记录与索引统计信息。
    # 入参：
    #   无显式入参。
    # 出参：JsonObject；JSON 字段映射。
    async def get_collection_stats(self) -> JsonObject:
        # 方法说明：_stats
        # 作用：为知识库统计建立默认字段结构。
        # 入参：
        #   无显式入参。
        # 出参：JsonObject；知识库统计的默认字段映射。
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

    # 方法说明：clear_collection
    # 作用：清空当前知识检索集合中的记录。
    # 入参：
    #   无显式入参。
    # 出参：bool；对应存储更新或删除是否完成。
    async def clear_collection(self) -> bool:
        return await asyncio.to_thread(self.vector_repository.clear_collection)

    # 方法说明：close
    # 作用：关闭当前组件拥有的客户端或连接，释放外部资源。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def close(self) -> None:
        await asyncio.to_thread(self.vector_repository.close)
        if self.lexical_repository is not None:
            await asyncio.to_thread(self.lexical_repository.close)

    # 方法说明：_split_into_documents
    # 作用：按文档分块策略切分正文，并绑定来源元数据。
    # 入参：
    #   text（str）：待解析、检索、切分或渲染的文本。
    #   metadata（JsonObject）：文档、消息或证据的来源与辅助元数据。
    #   requested_strategy（ChunkStrategyName）：请求使用的文档分块策略。
    # 出参：tuple[str, list[Document]]；文本字符串、带正文和来源元数据的文档片段的集合组成的元组。
    def _split_into_documents(
        self,
        text: str,
        metadata: JsonObject,
        requested_strategy: ChunkStrategyName,
    ) -> tuple[str, list[Document]]:
        return self.chunk_selector.split(text, metadata, requested_strategy)

    # 方法说明：_replace_document
    # 作用：替换同一文档的片段及其检索记录。
    # 入参：
    #   document_id（str）：文档标识。
    #   documents（list[Document]）：待处理的文档或文档片段集合。
    #   embeddings（list[list[float]]）：与文本顺序对应的向量集合。
    # 出参：JsonObject；JSON 字段映射。
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
            metadata["chunk_id"] = chunk_id
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
