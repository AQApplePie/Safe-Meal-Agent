"""协调上传文件的保存、解析与知识索引。"""

from __future__ import annotations
from safemeal.modules.knowledge.contracts.models import (
    DocumentIngestionResult,
    UploadedDocumentRecord,
)
from safemeal.shared.exceptions import ExternalServiceError, ConflictError

import asyncio
from hashlib import sha256


from safemeal.modules.knowledge.ports.ingestion.document_parser import DocumentParser
from safemeal.modules.knowledge.application.knowledge.chunking import ChunkStrategyName
from safemeal.modules.knowledge.application.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.modules.knowledge.application.upload.file_upload_service import (
    FileUploadService,
)


# 类说明（业务或基础设施实现类）：UploadedDocumentIngestionService
# 作用：实现上传文档解析分块与索引服务，封装该组件的业务处理与依赖协作。
class UploadedDocumentIngestionService:
    # 方法说明：__init__
    # 作用：初始化上传文档解析分块与索引服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   file_upload_service（FileUploadService）：文件校验与保存服务。
    #   document_parser（DocumentParser）：上传文档解析能力。
    #   document_knowledge（DocumentKnowledgeService）：文档摄取与检索业务服务。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        *,
        file_upload_service: FileUploadService,
        document_parser: DocumentParser,
        document_knowledge: DocumentKnowledgeService,
    ) -> None:
        # 实例属性说明：_file_upload_service
        # 作用：文件校验与保存服务。
        self._file_upload_service = file_upload_service
        # 实例属性说明：_document_parser
        # 作用：上传文档解析能力。
        self._document_parser = document_parser
        # 实例属性说明：_document_knowledge
        # 作用：文档摄取与检索业务服务。
        self._document_knowledge = document_knowledge

    # 方法说明：ingest
    # 作用：解析上传字节，按选定策略分块并写入知识检索存储。
    # 入参：
    #   original_filename（str | None）：上传文件的原始名称。
    #   content（bytes）：当前文件、消息或证据的正文内容。
    #   chunk_strategy（ChunkStrategyName）：请求使用的文档分块策略；默认值为 'auto'。
    #   tenant_id（str）：可信租户标识，用于业务数据隔离；默认值为 'default'。
    # 出参：DocumentIngestionResult；文档摄取结果。
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

    # 方法说明：delete
    # 作用：删除当前存储中的指定记录。
    # 入参：
    #   file_id（str）：上传文件标识。
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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
