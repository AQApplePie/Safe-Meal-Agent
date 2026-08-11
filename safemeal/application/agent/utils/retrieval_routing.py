"""Small deterministic routing guardrails for evidence-backed knowledge requests.

The LLM remains responsible for general planning.  These rules only protect explicit
document/retrieval intents from being silently converted into recipe-database calls.
"""

from __future__ import annotations

import re


_CROSS_DOCUMENT_MARKERS = (
    "综合资料",
    "综合知识库",
    "跨文档",
    "串起来",
    "归纳",
)
_DOCUMENT_MARKERS = (
    "按资料",
    "根据资料",
    "用资料",
    "知识资料",
    "项目样例",
    "原文",
    "知识库",
    "证据不全",
)
_STRUCTURED_DATA_MARKERS = (
    "数据库",
    "图谱",
    "结构化",
    "菜谱详情",
    "查一下",
    "查下",
    "先找",
    "推荐",
)


def knowledge_retrieval_tools(question: str) -> tuple[str, ...]:
    """Return required retrieval tools when the user clearly asks for KB evidence."""

    text = " ".join(question.strip().split())
    if not text:
        return ()

    wants_cross_document = any(marker in text for marker in _CROSS_DOCUMENT_MARKERS)
    wants_relationship_summary = bool(
        re.search(r"(之间|把.+和.+)(?:有啥|有什么|的)?(?:关系|联系)", text)
        or ("总结" in text and any(term in text for term in ("原则", "资料", "知识库")))
    )
    wants_document = any(marker in text for marker in _DOCUMENT_MARKERS)
    wants_document = wants_document or bool(
        re.search(r"(?:清蒸|蒸制|红烧|宫保|鱼香|麻婆).*(?:为什么|原理|鲜嫩)", text)
    )
    wants_document = wants_document or bool(
        "过敏" in text and any(marker in text for marker in ("替换", "替代", "证据"))
    )

    wants_milvus = wants_document
    wants_milvus = wants_milvus or wants_cross_document or wants_relationship_summary

    tools: list[str] = []
    if wants_milvus:
        tools.append("milvus_vector_search")
    return tuple(dict.fromkeys(tools))


def is_pure_knowledge_request(question: str) -> bool:
    """Whether a guarded retrieval intent has no simultaneous structured-data task."""

    if not knowledge_retrieval_tools(question):
        return False
    return not any(marker in question for marker in _STRUCTURED_DATA_MARKERS)


__all__ = ["is_pure_knowledge_request", "knowledge_retrieval_tools"]
