"""实现知识与菜谱检索基础设施适配。"""

import httpx
from math import isfinite
from time import perf_counter
from typing import List

from loguru import logger

from safemeal.shared.types import JsonObject


# 类说明（业务或基础设施实现类）：HttpDocumentReranker
# 作用：实现HTTP 文档重排适配器，封装该组件的业务处理与依赖协作。
class HttpDocumentReranker:
    # 方法说明：__init__
    # 作用：初始化HTTP 文档重排适配器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   enabled（bool）：目标行为或功能是否启用。
    #   provider（str | None）：当前选中的外部模型供应商。
    #   base_url（str | None）：外部服务的基础地址。
    #   endpoint（str | None）：外部 API 的接口路径。
    #   model（str | None）：当前调用使用的模型名称。
    #   api_key（str | None）：调用外部供应商所需的 API 凭据。
    #   top_n（int）：重排保留的最大候选数。
    #   timeout（float）：操作超时上限，单位秒。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        *,
        enabled: bool,
        provider: str | None,
        base_url: str | None,
        endpoint: str | None,
        model: str | None,
        api_key: str | None,
        top_n: int,
        timeout: float,
    ) -> None:
        # 实例属性说明：enabled
        # 作用：目标行为或功能是否启用。
        self.enabled = enabled
        # 实例属性说明：provider
        # 作用：当前选中的外部模型供应商。
        self.provider = provider.lower() if provider else None
        # 实例属性说明：base_url
        # 作用：外部服务的基础地址。
        self.base_url = base_url
        # 实例属性说明：endpoint
        # 作用：外部 API 的接口路径。
        self.endpoint = endpoint
        # 实例属性说明：model
        # 作用：当前调用使用的模型名称。
        self.model = model
        # 实例属性说明：api_key
        # 作用：调用外部供应商所需的 API 凭据。
        self.api_key = api_key
        # 实例属性说明：top_n
        # 作用：重排保留的最大候选数。
        self.top_n = top_n
        # 实例属性说明：timeout
        # 作用：操作超时上限，单位秒。
        self.timeout = timeout

        if not self.enabled:
            logger.info("DocumentReranker disabled via config")
            return

        if not self.provider or not self.api_key:
            logger.warning("DocumentReranker provider or API key not configured")
            # 实例属性说明：enabled
            # 作用：目标行为或功能是否启用。
            # 初始值：False。
            self.enabled = False
            return

    # 方法说明：rerank
    # 作用：在已召回片段范围内调用重排策略并返回排序结果。
    # 入参：
    #   query（str）：结构化查询条件或检索问题。
    #   documents（List[JsonObject]）：待处理的文档或文档片段集合。
    #   top_k（int）：检索返回的最大候选数。
    # 出参：List[JsonObject]；JSON 字段映射的集合。
    async def rerank(
        self,
        query: str,
        documents: List[JsonObject],
        top_k: int,
    ) -> List[JsonObject]:
        if not self.enabled or not documents:
            return documents[:top_k]

        started = perf_counter()
        logger.info(
            "knowledge.reranker.start provider={} model={} documents={} top_k={} "
            "timeout_seconds={}",
            self.provider,
            self.model,
            len(documents),
            top_k,
            self.timeout,
        )
        try:
            if self.provider == "custom":
                ranked = await self._custom_rerank(query, documents, top_k)
            elif self.provider == "jina":
                ranked = await self._jina_rerank(query, documents, top_k)
            elif self.provider == "voyage":
                ranked = await self._voyage_rerank(query, documents, top_k)
            else:
                logger.warning(f"Unsupported reranker provider: {self.provider}")
                return documents[:top_k]

            if ranked:
                logger.info(
                    "knowledge.reranker.completed provider={} model={} results={} "
                    "elapsed_ms={:.3f}",
                    self.provider,
                    self.model,
                    len(ranked),
                    (perf_counter() - started) * 1000,
                )
                return ranked
        except Exception as exc:
            logger.exception(
                "knowledge.reranker.failed provider={} model={} elapsed_ms={:.3f} "
                "error={}",
                self.provider,
                self.model,
                (perf_counter() - started) * 1000,
                exc,
            )
        return documents[:top_k]

    # 方法说明：_custom_rerank
    # 作用：调用对应供应商的重排接口并校验候选映射。
    # 入参：
    #   query（str）：结构化查询条件或检索问题。
    #   documents（List[JsonObject]）：待处理的文档或文档片段集合。
    #   top_k（int）：检索返回的最大候选数。
    # 出参：List[JsonObject]；JSON 字段映射的集合。
    async def _custom_rerank(
        self, query: str, documents: List[JsonObject], top_k: int
    ) -> List[JsonObject]:

        if not self.base_url:
            logger.error("Custom reranker requires RERANK_BASE_URL")
            return documents[:top_k]

        texts = [doc.get("content") or doc.get("text") or "" for doc in documents]

        url = f"{self.base_url.rstrip('/')}{self.endpoint}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # DashScope API 格式
        payload = {
            "model": self.model,
            "input": {
                "query": query,
                "documents": texts,
            },
            "parameters": {
                "return_documents": True,
                "top_n": min(self.top_n or top_k, len(documents)),
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        output = data.get("output", {})
        results = output.get("results", [])

        if not results:
            logger.warning("Custom reranker returned no results")
            return documents[:top_k]

        return self._process_rerank_results(results, documents, top_k)

    # 方法说明：_jina_rerank
    # 作用：调用对应供应商的重排接口并校验候选映射。
    # 入参：
    #   query（str）：结构化查询条件或检索问题。
    #   documents（List[JsonObject]）：待处理的文档或文档片段集合。
    #   top_k（int）：检索返回的最大候选数。
    # 出参：List[JsonObject]；JSON 字段映射的集合。
    async def _jina_rerank(
        self,
        query: str,
        documents: List[JsonObject],
        top_k: int,
    ) -> List[JsonObject]:
        texts = [doc.get("content") or doc.get("document") or "" for doc in documents]

        url = "https://api.jina.ai/v1/rerank"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "query": query,
            "documents": texts,
            "top_n": min(self.top_n or top_k, len(documents)),
        }

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        return self._process_rerank_results(results, documents, top_k)

    # 方法说明：_voyage_rerank
    # 作用：调用对应供应商的重排接口并校验候选映射。
    # 入参：
    #   query（str）：结构化查询条件或检索问题。
    #   documents（List[JsonObject]）：待处理的文档或文档片段集合。
    #   top_k（int）：检索返回的最大候选数。
    # 出参：List[JsonObject]；JSON 字段映射的集合。
    async def _voyage_rerank(
        self,
        query: str,
        documents: List[JsonObject],
        top_k: int,
    ) -> List[JsonObject]:
        texts = [doc.get("content") or doc.get("document") or "" for doc in documents]

        url = "https://api.voyageai.com/v1/rerank"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "query": query,
            "documents": texts,
            "top_k": min(self.top_n or top_k, len(documents)),
        }

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = data.get("data", [])
        return self._process_rerank_results(results, documents, top_k)

    # 方法说明：_process_rerank_results
    # 作用：校验重排索引与分数，将合法结果映射回原始候选片段。
    # 入参：
    #   results（List[JsonObject]）：多个操作或工具返回的结果集合。
    #   documents（List[JsonObject]）：待处理的文档或文档片段集合。
    #   top_k（int）：检索返回的最大候选数。
    # 出参：List[JsonObject]；JSON 字段映射的集合。
    def _process_rerank_results(
        self,
        results: List[JsonObject],
        documents: List[JsonObject],
        top_k: int,
    ) -> List[JsonObject]:
        reranked: list[JsonObject] = []
        seen: set[int] = set()
        for item in results:
            idx = item.get("index")
            score = item.get("relevance_score")
            if score is None:
                score = item.get("score")
            if type(idx) is not int or not 0 <= idx < len(documents) or idx in seen:
                continue
            if (
                not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not isfinite(score)
            ):
                continue
            doc = dict(documents[idx])
            doc["rerank_score"] = float(score)
            reranked.append(doc)
            seen.add(idx)
        reranked.extend(doc for index, doc in enumerate(documents) if index not in seen)
        return reranked[:top_k]
