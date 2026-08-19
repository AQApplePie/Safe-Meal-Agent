"""Application orchestration for uploaded knowledge documents."""

from __future__ import annotations

import asyncio
from hashlib import sha256

from pydantic import BaseModel

from safemeal.application.ports import DocumentParser
from safemeal.application.use_cases.knowledge.chunking import ChunkStrategyName
from safemeal.application.use_cases.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.application.use_cases.upload.file_upload_service import (
    FileUploadService,
    UploadSaveResult,
)
from safemeal.shared.types import JsonObject


class DocumentIngestionResult(BaseModel):
    """Stable result of saving and indexing one uploaded document."""

    success: bool
    file: UploadSaveResult
    ingestion: JsonObject
    parser: str
    checksum: str


class UploadedDocumentIngestionService:
    """Coordinate storage, parsing and indexing behind one application use case."""

    def __init__(
        self,
        *,
        file_upload_service: FileUploadService,
        document_parser: DocumentParser,
        document_knowledge: DocumentKnowledgeService,
    ) -> None:
        self._file_upload_service = file_upload_service
        self._document_parser = document_parser
        self._document_knowledge = document_knowledge

    async def ingest(
        self,
        *,
        original_filename: str | None,
        content: bytes,
        chunk_strategy: ChunkStrategyName = "auto",
        tenant_id: str = "default",
    ) -> DocumentIngestionResult:
        """Persist, parse and idempotently index an uploaded document."""

        saved = await self._file_upload_service.save(original_filename, content)
        parsed = await asyncio.to_thread(
            self._document_parser.parse,
            saved.original_name,
            content,
        )
        checksum = sha256(content).hexdigest()
        ingestion = await self._document_knowledge.ingest_text(
            parsed.text,
            metadata={
                "document_id": f"{tenant_id}:{saved.file_id or checksum}",
                "title": saved.original_name,
                "source": saved.file_path,
                "source_type": "upload",
                "parser": parsed.parser,
                "checksum": checksum,
                "tenant_id": tenant_id,
            },
            chunk_strategy=chunk_strategy,
        )
        return DocumentIngestionResult(
            success=bool(ingestion.get("add_count")),
            file=saved,
            ingestion=ingestion,
            parser=parsed.parser,
            checksum=checksum,
        )


__all__ = ["DocumentIngestionResult", "UploadedDocumentIngestionService"]
