"""实现知识与菜谱检索基础设施适配。"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from threading import RLock

from safemeal.shared.types import JsonObject


_WORD = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]")


# 方法说明：_tokens
# 作用：将查询文本转换为词法检索可用词项。
# 入参：
#   text（str）：待解析、检索、切分或渲染的文本。
# 出参：list[str]；用于词法查询的分词结果。
def _tokens(text: str) -> list[str]:
    raw = _WORD.findall(text.casefold())
    chinese = [item for item in raw if len(item) == 1 and "\u3400" <= item <= "\u9fff"]
    words = [item for item in raw if item not in chinese]
    return [*words, *chinese, *(a + b for a, b in zip(chinese, chinese[1:]))]


# 类说明（SQL 类）：SqliteBm25Repository
# 作用：实现SQLite FTS5 BM25 词法检索仓储的查询、写入或运行状态持久化。
class SqliteBm25Repository:
    # 方法说明：__init__
    # 作用：初始化SQLite FTS5 BM25 词法检索仓储，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   path（str | Path）：本次读取或写入的路径。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, path: str | Path) -> None:
        # 实例属性说明：path
        # 作用：本次读取或写入的路径。
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 实例属性说明：_lock
        # 作用：保护共享状态的互斥锁。
        self._lock = RLock()
        with self._connect() as connection:
            connection.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_bm25 USING fts5(
                    chunk_id UNINDEXED, document_id UNINDEXED, content,
                    original_content UNINDEXED, metadata_json UNINDEXED
                )"""
            )

    # 方法说明：_connect
    # 作用：创建并配置底层连接，供当前适配器访问外部存储。
    # 入参：
    #   无显式入参。
    # 出参：sqlite3.Connection；sqlite3.Connection。
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    # 方法说明：replace_document
    # 作用：用新片段替换同一文档的词法索引记录。
    # 入参：
    #   document_id（str）：文档标识。
    #   ids（list[str]）：待处理记录标识集合。
    #   documents（list[str]）：待处理的文档或文档片段集合。
    #   metadatas（list[JsonObject]）：文档、消息或证据的来源与辅助元数据。
    # 出参：bool；对应存储更新或删除是否完成。
    def replace_document(
        self,
        document_id: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[JsonObject],
    ) -> bool:
        if not (len(ids) == len(documents) == len(metadatas)):
            raise ValueError("BM25 documents, ids and metadata lengths must match")
        rows = [
            (
                chunk_id,
                document_id,
                " ".join(_tokens(content)),
                content,
                json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
            )
            for chunk_id, content, metadata in zip(ids, documents, metadatas)
        ]
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM knowledge_bm25 WHERE document_id=?", (document_id,)
            )
            connection.executemany(
                "INSERT INTO knowledge_bm25 VALUES (?, ?, ?, ?, ?)", rows
            )
        return True

    # 方法说明：search
    # 作用：通过SQLite FTS5 BM25 词法检索仓储按查询条件检索候选及其证据。
    # 入参：
    #   query（str）：结构化查询条件或检索问题。
    #   top_k（int）：检索返回的最大候选数；默认值为 10。
    #   filter_by（JsonObject | None）：当前检索使用的过滤条件或表达式；默认值为 None。
    # 出参：list[JsonObject]；JSON 字段映射的集合。
    def search(
        self, query: str, top_k: int = 10, filter_by: JsonObject | None = None
    ) -> list[JsonObject]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        tenant_id = (filter_by or {}).get("tenant_id") or "public"
        terms = _tokens(query)
        if not terms:
            return []
        expression = " OR ".join(f'"{item}"' for item in dict.fromkeys(terms))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT chunk_id, document_id, original_content, metadata_json,
                          -bm25(knowledge_bm25) AS score
                   FROM knowledge_bm25 WHERE knowledge_bm25 MATCH ?
                   AND COALESCE(json_extract(metadata_json, '$.tenant_id'), 'public') IN ('public', ?)
                   ORDER BY bm25(knowledge_bm25) LIMIT ?""",
                (expression, tenant_id, top_k),
            ).fetchall()
        results = [
            {
                "id": str(row["chunk_id"]),
                "document_id": str(row["document_id"]),
                "content": str(row["original_content"]),
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "score": float(row["score"]),
            }
            for row in rows
        ]
        return results

    # 方法说明：delete_documents
    # 作用：按文档标识删除检索片段及索引数据。
    # 入参：
    #   document_ids（list[str]）：待操作文档的标识集合。
    # 出参：bool；对应存储更新或删除是否完成。
    def delete_documents(self, document_ids: list[str]) -> bool:
        with self._lock, self._connect() as connection:
            connection.executemany(
                "DELETE FROM knowledge_bm25 WHERE document_id=?",
                [(item,) for item in document_ids],
            )
        return True

    # 方法说明：close
    # 作用：关闭当前组件拥有的客户端或连接，释放外部资源。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def close(self) -> None:
        return None


__all__ = ["SqliteBm25Repository"]
