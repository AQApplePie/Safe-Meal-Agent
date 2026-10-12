"""定义应用层依赖的能力端口。"""

from __future__ import annotations

from typing import Protocol

from safemeal.shared.types import JsonObject


# 类说明（接口类）：DocumentReranker
# 作用：定义文档片段重排接口的能力契约，供应用层与具体实现解耦。
class DocumentReranker(Protocol):
    # 字段说明：enabled
    # 作用：目标行为或功能是否启用。
    # 类型：bool。
    enabled: bool

    # 方法说明：rerank
    # 作用：在已召回片段范围内调用重排策略并返回排序结果。
    # 入参：
    #   query（str）：结构化查询条件或检索问题。
    #   documents（list[JsonObject]）：待处理的文档或文档片段集合。
    #   top_k（int）：检索返回的最大候选数。
    # 出参：list[JsonObject]；JSON 字段映射的集合。
    async def rerank(
        self,
        query: str,
        documents: list[JsonObject],
        top_k: int,
    ) -> list[JsonObject]: ...


__all__ = ["DocumentReranker"]
