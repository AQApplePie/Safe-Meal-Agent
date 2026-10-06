"""协调上传文件的保存、解析与知识索引。"""

from __future__ import annotations
from safemeal.application.contracts.upload.models import (
    DocumentIngestionResult,
    UploadedDocumentRecord,
)
from safemeal.application.exceptions import ExternalServiceError, ConflictError

import asyncio
from hashlib import sha256


from safemeal.application.ports import DocumentParser
from safemeal.application.service.knowledge.chunking import ChunkStrategyName
from safemeal.application.service.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.application.service.upload.file_upload_service import FileUploadService


class UploadedDocumentIngestionService:

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

        saved = await self._file_upload_service.save(original_filename, content)
        record = UploadedDocumentRecord(
            file=saved, tenant_id=tenant_id, document_id=f"{tenant_id}:{saved.file_id}"
        )
        await asyncio.to_thread(self._file_upload_service.save_document, record)
        try:
            parsed = await asyncio.to_thread(
                self._document_parser.parse, saved.original_name, content
            )
            checksum = sha256(content).hexdigest()
            ingestion = await self._document_knowledge.ingest_text(
                parsed.text,
                metadata={
                    "document_id": record.document_id,
                    "title": saved.original_name,
                    "source": saved.file_path,
                    "source_type": "upload",
                    "parser": parsed.parser,
                    "checksum": checksum,
                    "tenant_id": tenant_id,
                },
                chunk_strategy=chunk_strategy,
            )
            success = bool(ingestion.get("add_count"))
            record.status = "indexed" if success else "failed"
            await asyncio.to_thread(self._file_upload_service.save_document, record)
            return DocumentIngestionResult(
                success=success,
                file=saved,
                ingestion=ingestion,
                parser=parsed.parser,
                checksum=checksum,
            )
        except Exception:
            record.status = "failed"
            await asyncio.to_thread(self._file_upload_service.save_document, record)
            raise

    async def delete(self, *, file_id: str, tenant_id: str) -> None:
        record = await asyncio.to_thread(
            self._file_upload_service.get_document, file_id, tenant_id
        )
        if record.status == "processing":
            raise ConflictError("文件正在入库，请完成后再删除")
        record.status = "deleting"
        await asyncio.to_thread(self._file_upload_service.save_document, record)
        if not await self._document_knowledge.delete_document(record.document_id):
            raise ExternalServiceError("索引删除未完成，文件保留，可重试删除")
        await asyncio.to_thread(self._file_upload_service.delete_document_file, record)


__all__ = ["DocumentIngestionResult", "UploadedDocumentIngestionService"]
