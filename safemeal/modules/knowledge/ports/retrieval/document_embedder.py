"""定义应用层依赖的能力端口。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


# 类说明（接口类）：DocumentEmbedder
# 作用：定义文档与查询嵌入接口的能力契约，供应用层与具体实现解耦。
class DocumentEmbedder(Protocol):
    # 方法说明：embed_documents
    # 作用：将多个文档文本转换为与输入顺序一致的向量。
    # 入参：
    #   texts（Sequence[str]）：批量嵌入的文本序列。
    # 出参：list[list[float]]；数值的集合的集合。
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    # 方法说明：embed_query
    # 作用：将检索问题转换为查询向量。
    # 入参：
    #   text（str）：待解析、检索、切分或渲染的文本。
    # 出参：list[float]；数值的集合。
    def embed_query(self, text: str) -> list[float]: ...


__all__ = ["DocumentEmbedder"]
