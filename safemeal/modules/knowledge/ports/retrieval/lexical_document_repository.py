"""定义应用层依赖的能力端口。"""

from typing import Protocol
from safemeal.shared.types import JsonObject


class LexicalDocumentRepository(Protocol):
    def replace_document(
        self,
        document_id: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[JsonObject],
    ) -> bool: ...
    def search(
        self, query: str, top_k: int = 10, filter_by: JsonObject | None = None
    ) -> list[JsonObject]: ...
    def delete_documents(self, document_ids: list[str]) -> bool: ...
    def close(self) -> None: ...


__all__ = ["LexicalDocumentRepository"]
