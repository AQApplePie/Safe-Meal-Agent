"""
知识库模块的嵌入辅助工具。

提供一个简单的、兼容 OpenAI 的嵌入客户端，可以与 OpenAI、

DashScope (Qwen) 或任何公开兼容的 `/embeddings` 端点的服务进行通信。

我们特意避免依赖 LangChain 抽象层，以便能够针对仅支持部分 OpenAI 参数的供应商（例如 DashScope）微调请求负载。
"""

from typing import List, Optional, Sequence
from math import isfinite

from loguru import logger
from openai import OpenAI
import httpx


# 类说明（业务或基础设施实现类）：OpenAICompatibleDocumentEmbedder
# 作用：实现兼容 OpenAI 协议的文本嵌入适配器，封装该组件的业务处理与依赖协作。
class OpenAICompatibleDocumentEmbedder:
    # 方法说明：__init__
    # 作用：初始化兼容 OpenAI 协议的文本嵌入适配器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   model（str）：当前调用使用的模型名称。
    #   api_key（Optional[str]）：调用外部供应商所需的 API 凭据；默认值为 None。
    #   base_url（Optional[str]）：外部服务的基础地址；默认值为 None。
    #   dimension（Optional[int]）：嵌入向量的维度；默认值为 None。
    #   max_batch_size（int）：单批次处理的最大记录数；默认值为 64。
    #   request_timeout（Optional[float]）：单次外部请求超时，单位秒；默认值为 60.0。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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
        if not api_key or not api_key.strip():
            raise ValueError("Embedding API key must be explicitly configured")
        # 实例属性说明：model
        # 作用：当前调用使用的模型名称。
        self.model = model
        # 实例属性说明：dimension
        # 作用：嵌入向量的维度。
        self.dimension = dimension
        # 实例属性说明：max_batch_size
        # 作用：单批次处理的最大记录数。
        self.max_batch_size = max_batch_size
        # 实例属性说明：request_timeout
        # 作用：单次外部请求超时，单位秒。
        self.request_timeout = request_timeout

        try:
            # 实例属性说明：_client
            # 作用：底层外部服务客户端。
            self._client = OpenAI(api_key=api_key, base_url=base_url)
        except ValueError as exc:
            if "Unknown shceme for proxy URL" in str(exc):
                logger.warning(
                    "Invalid proxy env detected; disabling trust_env for OpenAI client: %s",
                    exc,
                )
                # 实例属性说明：_client
                # 作用：底层外部服务客户端。
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

    # 方法说明：embed_documents
    # 作用：将多个文档文本转换为与输入顺序一致的向量。
    # 入参：
    #   texts（Sequence[str]）：批量嵌入的文本序列。
    # 出参：List[List[float]]；数值的集合的集合。
    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        return self._embed(texts)

    # 方法说明：embed_query
    # 作用：将检索问题转换为查询向量。
    # 入参：
    #   text（str）：待解析、检索、切分或渲染的文本。
    # 出参：List[float]；数值的集合。
    def embed_query(self, text: str) -> List[float]:
        embeddings = self._embed([text])
        return embeddings[0] if embeddings else []

    # 方法说明：_embed
    # 作用：调用嵌入服务并校验响应索引、维度及数值完整性。
    # 入参：
    #   texts（Sequence[str]）：批量嵌入的文本序列。
    # 出参：List[List[float]]；数值的集合的集合。
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

                indexed: dict[int, list[float]] = {}
                for item in response.data:
                    index = item.index
                    vector = list(item.embedding)
                    if (
                        type(index) is not int
                        or not 0 <= index < len(batch)
                        or index in indexed
                        or not vector
                        or any(not isfinite(value) for value in vector)
                        or (self.dimension and len(vector) != self.dimension)
                    ):
                        raise ValueError("Invalid embedding response index or vector")
                    indexed[index] = vector
                if len(indexed) != len(batch):
                    raise ValueError("Embedding response is incomplete")
                embeddings_flat.extend(indexed[index] for index in range(len(batch)))

        except Exception as exc:
            logger.exception("Embedding request failed: %s", exc)
            raise

        result: List[List[float]] = [[] for _ in texts]

        for mapped_idx, vector in zip(index_map, embeddings_flat):
            result[mapped_idx] = vector

        return result
