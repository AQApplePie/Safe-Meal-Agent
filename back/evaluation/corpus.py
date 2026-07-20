"""Explicit preparation of the frozen retrieval benchmark corpus."""

from __future__ import annotations

import json
from pathlib import Path

from SafeMealAgent.back.bootstrap.container import AppContainer
from SafeMealAgent.back.evaluation.paths import data_path


def load_corpus(path: str | Path) -> list[dict[str, str]]:
    resolved = data_path(path, suffixes={".jsonl"})
    documents: list[dict[str, str]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(
        resolved.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        item = json.loads(line)
        required = {"document_id", "title", "content"}
        if not isinstance(item, dict) or not required <= item.keys():
            raise ValueError(
                f"{resolved}:{line_number}: corpus fields must include {sorted(required)}"
            )
        normalized = {key: str(item[key]).strip() for key in required}
        if not all(normalized.values()):
            raise ValueError(f"{resolved}:{line_number}: corpus fields cannot be blank")
        if normalized["document_id"] in seen:
            raise ValueError(
                f"duplicate corpus document_id: {normalized['document_id']}"
            )
        seen.add(normalized["document_id"])
        documents.append(normalized)
    return documents


async def prepare_corpus(
    documents: list[dict[str, str]],
    *,
    target: str = "both",
) -> dict[str, object]:
    """Ingest only when explicitly requested; normal evaluation never mutates indexes."""

    if target not in {"both", "milvus", "lightrag"}:
        raise ValueError("target must be both, milvus or lightrag")
    container = AppContainer()
    result: dict[str, object] = {"documents": len(documents), "target": target}
    try:
        if target in {"both", "milvus"}:
            knowledge_service = await container.get_knowledge_service()
            added = 0
            for item in documents:
                ok = await knowledge_service.add_document(
                    doc_id=item["document_id"],
                    title=item["title"],
                    content=item["content"],
                    metadata={"dataset": "agent_eval_v3", "category": "evaluation"},
                )
                added += int(ok)
            result["milvus_documents_replaced"] = added
        if target in {"both", "lightrag"}:
            lightrag_service = container.get_lightrag_service()
            payloads = [
                f"文档编号：{item['document_id']}\n标题：{item['title']}\n内容：{item['content']}"
                for item in documents
            ]
            insertion = await lightrag_service.insert_documents(payloads)
            result["lightrag"] = insertion.model_dump(mode="json")
        return result
    finally:
        await container.shutdown()


__all__ = ["load_corpus", "prepare_corpus"]
