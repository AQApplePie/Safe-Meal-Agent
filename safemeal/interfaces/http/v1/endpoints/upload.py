"""文件上传 HTTP 路由。

Router 只做协议转换和状态码处理，文件系统业务由 UploadService 统一完成。
"""

from hashlib import sha256

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from loguru import logger

from safemeal.application.use_cases.upload.service import (
    UploadNotFoundError,
    UploadSaveResult,
    UploadService,
    UploadSizeError,
    UploadTypeError,
)
from safemeal.interfaces.http.dependencies import (
    get_document_parser_registry,
    get_knowledge_service,
    get_upload_service,
)
from safemeal.application.use_cases.knowledge.service import KnowledgeService
from safemeal.application.use_cases.knowledge.chunking import ChunkStrategyName
from safemeal.infrastructure.ingestion.documents import (
    DocumentParseError,
    DocumentParserRegistry,
)
from safemeal.interfaces.http.models.upload import UploadResponse
from safemeal.shared.types import JsonObject

router = APIRouter()


def _translate_upload_error(exc: Exception) -> HTTPException:
    if isinstance(exc, UploadTypeError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, UploadSizeError):
        return HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        )
    if isinstance(exc, UploadNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    logger.exception("文件操作失败：{}", exc)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="文件操作失败",
    )


async def _save_upload(
    uploaded_file: UploadFile,
    service: UploadService,
) -> UploadSaveResult:
    try:
        content = await _read_upload(uploaded_file, service)
        result = await service.save(uploaded_file.filename, content)
        return result
    except Exception as exc:
        raise _translate_upload_error(exc) from exc


async def _read_upload(uploaded_file: UploadFile, service: UploadService) -> bytes:
    content = bytearray()
    while True:
        chunk = await uploaded_file.read(64 * 1024)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > service.max_size_bytes:
            max_mb = service.max_size_bytes / (1024 * 1024)
            raise UploadSizeError(f"文件太大，最大支持 {max_mb:g} MB")
    return bytes(content)


@router.post("/file", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    service: UploadService = Depends(get_upload_service),
) -> UploadResponse:
    """上传文档文件。"""
    return UploadResponse.from_result(await _save_upload(file, service))


@router.post("/file/ingest")
async def upload_and_ingest_file(
    file: UploadFile = File(...),
    chunk_strategy: ChunkStrategyName = Form(default="auto"),
    upload_service: UploadService = Depends(get_upload_service),
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
    document_parsers: DocumentParserRegistry = Depends(get_document_parser_registry),
) -> JsonObject:
    """保存、解析、分块、向量化并以幂等 document_id 写入知识库。"""

    try:
        content = await _read_upload(file, upload_service)
        saved = await upload_service.save(file.filename, content)
        parsed = await asyncio.to_thread(
            document_parsers.parse, saved.original_name, content
        )
        checksum = sha256(content).hexdigest()
        result = await knowledge_service.ingest_text(
            parsed.text,
            metadata={
                "document_id": saved.file_id or checksum,
                "title": saved.original_name,
                "source": saved.file_path,
                "source_type": "upload",
                "parser": parsed.parser,
                "checksum": checksum,
            },
            chunk_strategy=chunk_strategy,
        )
        return {
            "success": bool(result.get("add_count")),
            "file": saved.model_dump(mode="json"),
            "ingestion": result,
            "parser": parsed.parser,
            "checksum": checksum,
        }
    except DocumentParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise _translate_upload_error(exc) from exc


@router.get("/files/{filename}")
async def get_uploaded_file(
    filename: str,
    service: UploadService = Depends(get_upload_service),
) -> FileResponse:
    try:
        return FileResponse(service.resolve(filename))
    except Exception as exc:
        raise _translate_upload_error(exc) from exc


@router.delete("/{file_id}")
async def delete_uploaded_file(
    file_id: str,
    service: UploadService = Depends(get_upload_service),
) -> JsonObject:
    try:
        service.delete(file_id)
        return {"success": True, "message": "文件删除成功"}
    except Exception as exc:
        raise _translate_upload_error(exc) from exc
