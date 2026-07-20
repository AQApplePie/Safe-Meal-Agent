"""
LightRAG infrastructure service

基于 Docker build 时生成的 LightRAG JSON 文件提供问答检索功能
- 使用预生成的索引文件（kv_store_*.json, vdb_*.json, graph_chunk_entity_relation.graphml）
- 支持多种检索模式：naive, local, global, hybrid
- 支持流式响应
- 支持增量文档插入
"""

import asyncio
import json
import inspect
import re
from time import perf_counter
from typing import AsyncGenerator, List, Optional
from pathlib import Path

from SafeMealAgent.back.infrastructure.retrieval.lightrag import LightRAG, QueryParam
from lightrag.base import DocStatus
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc, compute_mdhash_id
from lightrag.kg.shared_storage import initialize_pipeline_status
import numpy as np

from SafeMealAgent.back.config.settings import settings
from SafeMealAgent.back.application.contracts.lightrag import LightRAGInsertResult, SearchMode
from SafeMealAgent.back.infrastructure.operations.logging import get_logger
from SafeMealAgent.back.infrastructure.retrieval.lightrag.index_stats import collect_index_stats
from SafeMealAgent.back.shared.types import JsonObject

logger = get_logger(service="lightrag-service")

_DUPLICATE_DOCUMENT = re.compile(r"Original doc_id:\s*([^,\s]+)")


def _document_is_processed(status: object) -> bool:
    value = status.get("status") if isinstance(status, dict) else getattr(status, "status", None)
    if isinstance(value, DocStatus):
        return value == DocStatus.PROCESSED
    return str(value).casefold() == DocStatus.PROCESSED.value.casefold()


async def _lightrag_llm_model_func(
    prompt: str,
    system_prompt: Optional[str] = None,
    history_messages: Optional[List] = None,
    **kwargs,
) -> str:
    """Module-level callback so LightRAG can safely deepcopy its config."""

    return await openai_complete_if_cache(
        model=settings.OPENAI_MODEL,
        prompt=prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_API_BASE,
        **kwargs,
    )


async def _lightrag_embedding_func(texts: List[str]) -> np.ndarray:
    """Module-level embedding callback without a bound service instance."""

    api_key = settings.EMBEDDING_API_KEY or settings.OPENAI_API_KEY
    base_url = settings.EMBEDDING_BASE_URL or settings.OPENAI_API_BASE
    embed_func = getattr(openai_embed, "func", openai_embed)
    return await embed_func(
        texts=texts,
        model=settings.EMBEDDING_MODEL,
        api_key=api_key,
        base_url=base_url,
    )


def _infer_embedding_dim_from_working_dir(working_dir: str) -> Optional[int]:
    """
    尽力从预生成的 LightRAG VDB 文件中推断嵌入维度。

    我们的构建流程将嵌入维度存储在 `vdb_*.json` 文件中（顶层 `embedding_dim`），
    当运行时环境变量 `EMBEDDING_DIMENSION` 未设置或为空时，这是最可靠的来源。
    """

    for file_name in ("vdb_chunks.json", "vdb_entities.json", "vdb_relationships.json"):
        path = Path(working_dir) / file_name
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            dim = payload.get("embedding_dim") if isinstance(payload, dict) else None
            if isinstance(dim, int) and dim > 0:
                return dim
        except Exception:
            continue
    return None


class LightRAGService:
    """
    LightRAG 问答检索服务

    功能：
    - 基于预生成的索引文件进行问答检索
    - 支持多种检索模式（naive, local, global, hybrid）
    - 支持流式和非流式响应
    - 支持增量文档插入
    """

    def __init__(
        self,
        working_dir: Optional[str] = None,
        default_mode: SearchMode = "hybrid",
        default_top_k: int = 10,
    ):
        """
        初始化 LightRAG 服务

        Parameters
        ----------
        working_dir : str, optional
            LightRAG 工作目录（包含预生成的 JSON 文件）
        default_mode : SearchMode, optional
            默认检索模式
        default_top_k : int, optional
            默认返回结果数量
        """
        self.working_dir = working_dir or settings.LIGHTRAG_WORKING_DIR
        self.default_mode = default_mode
        self.default_top_k = default_top_k

        self.rag: Optional[LightRAG] = None
        self.initialized = False
        self._initialization_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

        logger.info(f"LightRAG 服务初始化，工作目录: {self.working_dir}")

    async def _llm_model_func(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history_messages: Optional[List] = None,
        **kwargs,
    ) -> str:
        """
        LLM 模型函数

        Parameters
        ----------
        prompt : str
            用户提示词
        system_prompt : str, optional
            系统提示词
        history_messages : list, optional
            历史消息
        **kwargs : dict
            其他参数

        Returns
        -------
        str
            LLM 生成的文本
        """
        return await _lightrag_llm_model_func(
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            **kwargs,
        )

    async def _embedding_func(self, texts: List[str]) -> np.ndarray:
        """
        Embedding 函数

        Parameters
        ----------
        texts : List[str]
            要嵌入的文本列表

        Returns
        -------
        np.ndarray
            嵌入向量数组
        """
        return await _lightrag_embedding_func(texts)

    async def initialize(self) -> None:
        """
        初始化 LightRAG 实例

        会检查工作目录是否存在预生成的索引文件：
        - graph_chunk_entity_relation.graphml
        - kv_store_*.json
        - vdb_*.json
        """

        if self.initialized:
            logger.info(
                "knowledge.lightrag_initialize.skipped reason=already_initialized"
            )
            return

        async with self._initialization_lock:
            if self.initialized:
                logger.info(
                    "knowledge.lightrag_initialize.skipped reason=initialized_by_peer"
                )
                return
            await self._initialize_once()

    async def _initialize_once(self) -> None:
        """Initialize storages once while the caller holds the lifecycle lock."""

        started = perf_counter()
        logger.info(
            "knowledge.lightrag_initialize.start working_dir={} embedding_model={} "
            "embedding_dimension={} llm_model={}",
            self.working_dir,
            settings.EMBEDDING_MODEL,
            settings.EMBEDDING_DIMENSION,
            settings.OPENAI_MODEL,
        )
        try:
            if not Path(self.working_dir).exists():
                logger.warning(f"工作目录不存在，创建: {self.working_dir}")
                Path(self.working_dir).mkdir(parents=True, exist_ok=True)

            required_files = [
                "graph_chunk_entity_relation.graphml",
                "kv_store_doc_status.json",
                "kv_store_full_docs.json",
                "kv_store_text_chunks.json",
                "vdb_chunks.json",
                "vdb_entities.json",
                "vdb_relationships.json",
            ]

            missing_files = []

            for file_name in required_files:
                file_path = Path(self.working_dir) / file_name
                if not file_path.exists():
                    missing_files.append(file_name)

            if missing_files:
                logger.warning(
                    f"警告：以下索引文件不存在，查询可能返回空结果:\n"
                    f"{', '.join(missing_files)}\n"
                    f"请确保 Docker build 时已正确初始化 LightRAG"
                )
            else:
                logger.info("✓ 所有预生成的索引文件已存在")
                # 显示文件大小
                for file_name in required_files:
                    file_path = Path(self.working_dir) / file_name
                    file_size = file_path.stat().st_size
                    logger.info(f"  - {file_name}: {file_size / 1024:.2f} KB")

            # 获取 embedding 维度
            embedding_dim: Optional[int] = _infer_embedding_dim_from_working_dir(
                self.working_dir
            )
            if embedding_dim is None:
                embedding_dim = settings.EMBEDDING_DIMENSION
                logger.info(f"Embedding 维度(配置): {embedding_dim}")
            else:
                logger.info(f"Embedding 维度(从索引推断): {embedding_dim}")

            logger.info(f"LLM 模型: {settings.OPENAI_MODEL}")
            logger.info(f"Embedding 模型: {settings.EMBEDDING_MODEL}")

            self.rag = LightRAG(
                working_dir=self.working_dir,
                llm_model_func=_lightrag_llm_model_func,
                embedding_func=EmbeddingFunc(
                    embedding_dim=embedding_dim,
                    max_token_size=settings.LIGHTRAG_MAX_TOKEN_SIZE,
                    func=_lightrag_embedding_func,
                ),
            )

            # 初始化存储（会加载预生成的索引文件）
            logger.info("加载预生成的索引文件...")
            await self.rag.initialize_storages()
            logger.info(
                "knowledge.lightrag_storage.initialized working_dir={} "
                "elapsed_ms={:.3f}",
                self.working_dir,
                (perf_counter() - started) * 1000,
            )
            await initialize_pipeline_status()

            self.initialized = True
            logger.info(
                "knowledge.lightrag_initialize.completed working_dir={} "
                "elapsed_ms={:.3f}",
                self.working_dir,
                (perf_counter() - started) * 1000,
            )
        except Exception as e:
            logger.exception(
                "knowledge.lightrag_initialize.failed working_dir={} "
                "elapsed_ms={:.3f} error={}",
                self.working_dir,
                (perf_counter() - started) * 1000,
                e,
            )
            partially_initialized = self.rag
            self.rag = None
            self.initialized = False
            if partially_initialized is not None:
                try:
                    await partially_initialized.finalize_storages()
                except Exception:
                    logger.exception(
                        "knowledge.lightrag_initialize.rollback_failed working_dir={}",
                        self.working_dir,
                    )
            raise RuntimeError(f"LightRAG 初始化失败: {str(e)}") from e

    async def query(
        self,
        query: str,
        mode: Optional[SearchMode] = None,
        top_k: Optional[int] = None,
        stream: bool = False,
    ) -> str | AsyncGenerator[str, None]:
        """
        执行问答检索

        Parameters
        ----------
        query : str
            查询问题
        mode : SearchMode, optional
            检索模式（naive/local/global/hybrid），默认使用配置的模式
        top_k : int, optional
            返回结果数量，默认使用配置的值
        stream : bool, optional
            是否使用流式响应

        Returns
        -------
        str | AsyncGenerator[str, None]
            如果 stream=False，返回完整答案字符串
            如果 stream=True，返回异步生成器
        """

        request_started = perf_counter()
        logger.info(
            "knowledge.lightrag_query.start mode={} top_k={} stream={} query_chars={}",
            mode or self.default_mode,
            top_k or self.default_top_k,
            stream,
            len(query),
        )
        await self.initialize()
        rag = self.rag
        if rag is None:
            raise RuntimeError("LightRAG initialized without a runtime instance")

        retrieval_mode = mode or self.default_mode
        k = top_k or self.default_top_k

        try:
            logger.info(f"执行查询 | 模式: {retrieval_mode} | Top-K: {k}")
            param = QueryParam(mode=retrieval_mode, top_k=k, stream=stream)

            response = await rag.aquery(query, param=param)
            logger.info(
                "knowledge.lightrag_query.provider_completed mode={} top_k={} "
                "elapsed_ms={:.3f}",
                retrieval_mode,
                k,
                (perf_counter() - request_started) * 1000,
            )

            if stream:
                if inspect.isasyncgen(response):
                    logger.info("返回流式响应")
                    return response

                async def one_shot() -> AsyncGenerator[str, None]:
                    if response:
                        yield str(response)

                logger.info(
                    "stream=true but got non-generator response; "
                    "wrapped as one-shot stream"
                )
                return one_shot()

            if response is None:
                logger.warning(
                    "Non-stream query returned None; treating as empty response"
                )
                return ""
            response_text = str(response)
            logger.info(
                "knowledge.lightrag_query.completed mode={} top_k={} "
                "response_chars={} elapsed_ms={:.3f}",
                retrieval_mode,
                k,
                len(response_text),
                (perf_counter() - request_started) * 1000,
            )
            return response_text
        except Exception as e:
            logger.exception(
                "knowledge.lightrag_query.failed mode={} top_k={} "
                "elapsed_ms={:.3f} error={}",
                retrieval_mode,
                k,
                (perf_counter() - request_started) * 1000,
                e,
            )
            raise RuntimeError(f"LightRAG 查询失败: {str(e)}")

    async def insert_documents(
        self,
        documents: List[str],
        batch_size: int = 10,
    ) -> LightRAGInsertResult:
        """
        增量插入文档到 LightRAG

        Parameters
        ----------
        documents : List[str]
            要插入的文档列表
        batch_size : int, optional
            批量处理大小（每处理 batch_size 个文档记录一次进度）

        Returns
        -------
        LightRAGInsertResult
            插入结果统计
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        await self.initialize()
        rag = self.rag
        if rag is None:
            raise RuntimeError("LightRAG initialized without a runtime instance")

        async with self._write_lock:
            try:
                logger.info(f"开始插入 {len(documents)} 个文档")
                await self._remove_verified_duplicate_failures(rag)

                success_count = 0
                already_present_count = 0
                failed_count = 0
                errors = []

                for i, doc in enumerate(documents):
                    try:
                        document_id = compute_mdhash_id(doc, prefix="doc-")
                        current = await rag.aget_docs_by_ids(document_id)
                        if _document_is_processed(current.get(document_id)):
                            success_count += 1
                            already_present_count += 1
                            logger.info(
                                "文档 {} 已存在且处理完成，按幂等成功计数",
                                i + 1,
                            )
                            continue
                        track_id = await rag.ainsert(doc)
                        statuses = await rag.aget_docs_by_track_id(track_id)
                        failed = [
                            status
                            for status in statuses.values()
                            if status.status == DocStatus.FAILED
                        ]
                        if failed:
                            details = "; ".join(
                                status.error_msg or "unknown LightRAG pipeline error"
                                for status in failed
                            )
                            raise RuntimeError(details)
                        if not statuses or any(
                            status.status != DocStatus.PROCESSED
                            for status in statuses.values()
                        ):
                            state = (
                                ", ".join(
                                    sorted(
                                        {
                                            status.status.value
                                            for status in statuses.values()
                                        }
                                    )
                                )
                                or "missing"
                            )
                            raise RuntimeError(
                                f"LightRAG pipeline did not finish successfully: {state}"
                            )
                        success_count += 1

                        if (i + 1) % batch_size == 0:
                            logger.info(f"已插入 {i + 1}/{len(documents)} 个文档")

                    except Exception as e:
                        duplicate = _DUPLICATE_DOCUMENT.search(str(e))
                        if duplicate:
                            existing = await rag.aget_docs_by_ids(duplicate.group(1))
                            status = existing.get(duplicate.group(1))
                            if _document_is_processed(status):
                                success_count += 1
                                already_present_count += 1
                                logger.info(
                                    "文档 {} 已存在且处理完成，按幂等成功计数",
                                    i + 1,
                                )
                                continue
                        failed_count += 1
                        error_msg = f"文档 {i + 1} 插入失败: {str(e)}"
                        errors.append(error_msg)
                        logger.error(error_msg)
                logger.info(
                    f"文档插入完成 | 成功: {success_count} | 失败: {failed_count}"
                )

                return LightRAGInsertResult(
                    total=len(documents),
                    success=success_count,
                    already_present=already_present_count,
                    failed=failed_count,
                    errors=errors,
                )
            except Exception as e:
                logger.error(f"批量插入文档失败: {str(e)}", exc_info=True)
                raise RuntimeError(f"文档插入失败: {str(e)}") from e

    @staticmethod
    async def _remove_verified_duplicate_failures(rag: LightRAG) -> None:
        """Remove stale duplicate-error rows only when their original is processed."""

        storage = getattr(rag, "doc_status", None)
        if storage is None:
            return
        failed = await storage.get_docs_by_status(DocStatus.FAILED)
        candidates: dict[str, str] = {}
        for failed_id, status in failed.items():
            message = (
                status.get("error_msg", "")
                if isinstance(status, dict)
                else getattr(status, "error_msg", "")
            )
            duplicate = _DUPLICATE_DOCUMENT.search(str(message or ""))
            if duplicate:
                candidates[failed_id] = duplicate.group(1)
        if not candidates:
            return
        originals = await rag.aget_docs_by_ids(sorted(set(candidates.values())))
        removable = [
            failed_id
            for failed_id, original_id in candidates.items()
            if _document_is_processed(originals.get(original_id))
        ]
        if not removable:
            return
        await storage.delete(removable)
        await storage.index_done_callback()
        logger.info("清理 {} 条已验证的重复文档失败状态", len(removable))

    async def cleanup(self) -> None:
        """清理资源"""
        async with self._initialization_lock:
            rag = self.rag
            if rag is None:
                self.initialized = False
                return
            try:
                await rag.finalize_storages()
                logger.info("LightRAG 资源已释放")
            except Exception:
                logger.exception(
                    "knowledge.lightrag_cleanup.failed working_dir={}",
                    self.working_dir,
                )
                raise
            finally:
                self.rag = None
                self.initialized = False

    def get_index_stats(self) -> JsonObject:
        """Return index file statistics without changing service state."""

        return collect_index_stats(
            self.working_dir,
            initialized=self.initialized,
        )
