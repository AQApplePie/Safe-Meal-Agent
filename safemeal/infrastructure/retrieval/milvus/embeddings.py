"""
知识库模块的嵌入辅助工具。

提供一个简单的、兼容 OpenAI 的嵌入客户端，可以与 OpenAI、

DashScope (Qwen) 或任何公开兼容的 `/embeddings` 端点的服务进行通信。

我们特意避免依赖 LangChain 抽象层，以便能够针对仅支持部分 OpenAI 参数的供应商（例如 DashScope）微调请求负载。
"""

from typing import List, Optional, Sequence

from loguru import logger
from openai import OpenAI
import httpx


class OpenAICompatibleEmbeddings:
    """Thin wrapper around the official OpenAI client for embedding requests."""

    def __init__(
        self,
        *,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        dimension: Optional[int] = None,
        max_batch_size: int = 64,
        request_timeout: Optional[float] = 60.0,
    ) -> None:
        self.model = model
        self.dimension = dimension
        self.max_batch_size = max_batch_size
        self.request_timeout = request_timeout

        try:
            self._client = OpenAI(api_key=api_key, base_url=base_url)
        except ValueError as exc:
            # Some environments set ALL_PROXY to an unsupported scheme like `socks://...`,
            # which makes httpx (and therefore the OpenAI client) crash at import-time.
            # Fall back to a client that ignores env proxies to keep the KB functional.

            if "Unknown shceme for proxy URL" in str(exc):
                logger.warning(
                    "Invalid proxy env detected; disabling trust_env for OpenAI client: %s",
                    exc,
                )
                self._client = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    http_client=httpx.Client(trust_env=False),
                )
            else:
                raise
        logger.info(
            "Initialised OpenAI-compatible embeddings client (model=%s, base_url=%s)",
            model,
            base_url or "https://api.openai.com/v1",
        )

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        """Embed a sequence of texts."""
        return self._embed(texts)

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query string."""
        embeddings = self._embed([text])
        return embeddings[0] if embeddings else []

    def _embed(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []

        ordered_inputs: List[str] = []
        index_map: List[int] = []
        for idx, text in enumerate(texts):
            value = (text or "").strip()
            if not value:
                value = " "
            ordered_inputs.append(value)
            index_map.append(idx)
        embeddings_flat: List[List[float]] = []

        try:
            for start in range(0, len(ordered_inputs), self.max_batch_size):
                batch = ordered_inputs[start : start + self.max_batch_size]
                response = self._client.embeddings.create(
                    model=self.model, input=batch, timeout=self.request_timeout
                )

                for item in response.data:
                    vector = list(item.embedding)
                    if self.dimension and len(vector) != self.dimension:
                        logger.warning(
                            "Embedding dimension mismatch: expected=%s actual=%s",
                            self.dimension,
                            len(vector),
                        )
                    embeddings_flat.append(vector)

        except Exception as exc:
            logger.exception("Embedding request failed: %s", exc)
            raise

        result: List[List[float]] = [[] for _ in texts]

        for mapped_idx, vector in zip(index_map, embeddings_flat):
            result[mapped_idx] = vector

        if any(not vec for vec in result):
            fallback_dim = (
                len(embeddings_flat[0]) if embeddings_flat else (self.dimension or 0)
            )
            zero_vec = [0.0] * fallback_dim
            for idx, vec in enumerate(result):
                if not vec:
                    result[idx] = zero_vec

        return result
