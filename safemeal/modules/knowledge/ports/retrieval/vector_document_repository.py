"""定义应用层依赖的能力端口。"""

from __future__ import annotations

from typing import Protocol

from safemeal.shared.types import JsonObject


# 类说明（接口类）：VectorDocumentRepository
# 作用：定义向量文档存储与检索接口的能力契约，供应用层与具体实现解耦。
class VectorDocumentRepository(Protocol):
    # 方法说明：add_documents
    # 作用：将文档片段及元数据加入检索存储。
    # 入参：
    #   ids（list[str]）：待处理记录标识集合。
    #   embeddings（list[list[float]]）：与文本顺序对应的向量集合。
    #   documents（list[str]）：待处理的文档或文档片段集合。
    #   metadatas（list[JsonObject] | None）：文档、消息或证据的来源与辅助元数据；默认值为 None。
    # 出参：bool；对应存储更新或删除是否完成。
    def add_documents(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[JsonObject] | None = None,
    ) -> bool: ...

    # 方法说明：replace_document
    # 作用：用新片段替换同一文档的词法索引记录。
    # 入参：
    #   document_id（str）：文档标识。
    #   ids（list[str]）：待处理记录标识集合。
    #   embeddings（list[list[float]]）：与文本顺序对应的向量集合。
    #   documents（list[str]）：待处理的文档或文档片段集合。
    #   metadatas（list[JsonObject]）：文档、消息或证据的来源与辅助元数据。
    # 出参：bool；对应存储更新或删除是否完成。
    def replace_document(
        self,
        document_id: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[JsonObject],
    ) -> bool: ...

    # 方法说明：search
    # 作用：通过向量文档存储与检索接口按查询条件检索候选及其证据。
    # 入参：
    #   query_embedding（list[float]）：检索问题对应的向量。
    #   top_k（int）：检索返回的最大候选数；默认值为 10。
    #   filter_expr（str | None）：当前检索使用的过滤条件或表达式；默认值为 None。
    # 出参：list[JsonObject]；JSON 字段映射的集合。
    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_expr: str | None = None,
    ) -> list[JsonObject]: ...

    # 方法说明：delete_documents
    # 作用：按文档标识删除检索片段及索引数据。
    # 入参：
    #   document_ids（list[str]）：待操作文档的标识集合。
    # 出参：bool；对应存储更新或删除是否完成。
    def delete_documents(self, document_ids: list[str]) -> bool: ...

    # 方法说明：get_collection_stats
    # 作用：查询知识检索集合的记录与索引统计信息。
    # 入参：
    #   无显式入参。
    # 出参：JsonObject；JSON 字段映射。
    def get_collection_stats(self) -> JsonObject: ...

    # 方法说明：clear_collection
    # 作用：清空当前知识检索集合中的记录。
    # 入参：
    #   无显式入参。
    # 出参：bool；对应存储更新或删除是否完成。
    def clear_collection(self) -> bool: ...

    # 方法说明：close
    # 作用：关闭当前组件拥有的客户端或连接，释放外部资源。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def close(self) -> None: ...


__all__ = ["VectorDocumentRepository"]
