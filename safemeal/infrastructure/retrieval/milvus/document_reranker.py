"""实现知识与菜谱检索基础设施适配。"""

import httpx
from time import perf_counter
from typing import List

from loguru import logger

from safemeal.shared.types import JsonObject


class HttpDocumentReranker:

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
        self.enabled = enabled
        self.provider = provider.lower() if provider else None
        self.base_url = base_url
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.top_n = top_n
        self.timeout = timeout

        if not self.enabled:
            logger.info("DocumentReranker disabled via config")
            return

        if not self.provider or not self.api_key:
            logger.warning("DocumentReranker provider or API key not configured")
            self.enabled = False
            return

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

        # 重新排序文档
        reranked = []
        for item in results:
            idx = item.get("index")
            score = item.get("relevance_score") or item.get("score")

            if idx is not None and 0 <= idx < len(documents):
                doc: JsonObject = dict(documents[idx])
                if score is not None:
                    doc["rerank_score"] = float(score)
                reranked.append(doc)

        # 添加未被重排的文档
        seen_ids = {doc.get("chunk_id") or doc.get("id") for doc in reranked}
        for doc in documents:
            doc_id = doc.get("chunk_id") or doc.get("id")
            if doc_id not in seen_ids:
                reranked.append(doc)

        return reranked[:top_k]

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

    def _process_rerank_results(
        self,
        results: List[JsonObject],
        documents: List[JsonObject],
        top_k: int,
    ) -> List[JsonObject]:
        reranked = []

        for item in results:
            idx = item.get("index")
            score = item.get("relevance_score") or item.get("score")

            if idx is not None and 0 <= idx < len(documents):
                doc: JsonObject = dict(documents[idx])
                if score is not None:
                    doc["rerank_score"] = float(score)
                reranked.append(doc)

        # 添加未被重排的文档
        seen_ids = {doc.get("chunk_id") or doc.get("id") for doc in reranked}
        for doc in documents:
            doc_id = doc.get("chunk_id") or doc.get("id")
            if doc_id not in seen_ids:
                reranked.append(doc)

        return reranked[:top_k]
