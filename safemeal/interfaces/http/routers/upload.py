"""文件上传 HTTP 路由。

Router 只做协议转换和状态码处理，文件系统业务由 FileUploadService 统一完成。
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from loguru import logger

from safemeal.application.use_cases.upload.file_upload_service import (
    UploadNotFoundError,
    UploadSaveResult,
    FileUploadService,
    UploadSizeLimitError,
    InvalidUploadError,
)
from safemeal.interfaces import (
    get_file_upload_service,
    get_uploaded_document_ingestion_service,
)
from safemeal.application.use_cases.knowledge.chunking import ChunkStrategyName
from safemeal.application.ports import DocumentParseError
from safemeal.application.use_cases.upload.uploaded_document_ingestion_service import (
    UploadedDocumentIngestionService,
)
from safemeal.interfaces import UploadResponse
from safemeal.shared.types import JsonObject
from safemeal.bootstrap.application_container import ApplicationContainer
from safemeal.interfaces.http.dependencies import get_container
from safemeal.interfaces.http.authentication import Principal, get_current_principal
from safemeal.application.use_cases.upload.ingestion_queue import IngestionJob

router = APIRouter()


def _translate_upload_error(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidUploadError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, UploadSizeLimitError):
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
    file_upload_service: FileUploadService,
) -> UploadSaveResult:
    try:
        content = await _read_upload(uploaded_file, file_upload_service)
        result = await file_upload_service.save(uploaded_file.filename, content)
        return result
    except Exception as exc:
        raise _translate_upload_error(exc) from exc


async def _read_upload(
    uploaded_file: UploadFile, file_upload_service: FileUploadService
) -> bytes:
    content = bytearray()
    while True:
        chunk = await uploaded_file.read(64 * 1024)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > file_upload_service.max_size_bytes:
            max_mb = file_upload_service.max_size_bytes / (1024 * 1024)
            raise UploadSizeLimitError(f"文件太大，最大支持 {max_mb:g} MB")
    return bytes(content)


@router.post("/file", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    file_upload_service: FileUploadService = Depends(get_file_upload_service),
) -> UploadResponse:
    """上传文档文件。"""
    return UploadResponse.from_result(await _save_upload(file, file_upload_service))


@router.post("/file/ingest")
async def upload_and_ingest_file(
    file: UploadFile = File(...),
    chunk_strategy: ChunkStrategyName = Form(default="auto"),
    file_upload_service: FileUploadService = Depends(get_file_upload_service),
    ingestion: UploadedDocumentIngestionService = Depends(
        get_uploaded_document_ingestion_service
    ),
    principal: Principal = Depends(get_current_principal),
) -> JsonObject:
    """Save and ingest a document through the application use case."""

    try:
        content = await _read_upload(file, file_upload_service)
        result = await ingestion.ingest(
            original_filename=file.filename,
            content=content,
            chunk_strategy=chunk_strategy,
            tenant_id=principal.tenant_id,
        )
        return result.model_dump(mode="json")
    except DocumentParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise _translate_upload_error(exc) from exc


@router.post("/file/ingest-async", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_uploaded_document(
    file: UploadFile = File(...),
    chunk_strategy: ChunkStrategyName = Form(default="auto"),
    file_upload_service: FileUploadService = Depends(get_file_upload_service),
    container: ApplicationContainer = Depends(get_container),
    principal: Principal = Depends(get_current_principal),
) -> JsonObject:
    """Queue parsing, OCR and indexing outside the request lifecycle."""

    if container.ingestion_queue is None:
        raise HTTPException(status_code=503, detail="后台摄取队列未配置")
    content = await _read_upload(file, file_upload_service)
    job = IngestionJob.create(
        tenant_id=principal.tenant_id,
        filename=file.filename or "upload",
        content=content,
        chunk_strategy=chunk_strategy,
    )
    await container.ingestion_queue.enqueue(job)
    return {"job_id": job.job_id, "status": job.status}


@router.get("/ingestion-jobs/{job_id}")
async def get_ingestion_job(
    job_id: str,
    container: ApplicationContainer = Depends(get_container),
    principal: Principal = Depends(get_current_principal),
) -> JsonObject:
    if container.ingestion_queue is None:
        raise HTTPException(status_code=503, detail="后台摄取队列未配置")
    job = await container.ingestion_queue.get(job_id)
    if job is None or job.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail="摄取任务不存在")
    return job.model_dump(mode="json", exclude={"content_hex"})


@router.get("/files/{filename}")
async def get_uploaded_file(
    filename: str,
    file_upload_service: FileUploadService = Depends(get_file_upload_service),
) -> FileResponse:
    try:
        return FileResponse(file_upload_service.resolve(filename))
    except Exception as exc:
        raise _translate_upload_error(exc) from exc


@router.delete("/{file_id}")
async def delete_uploaded_file(
    file_id: str,
    file_upload_service: FileUploadService = Depends(get_file_upload_service),
) -> JsonObject:
    try:
        file_upload_service.delete(file_id)
        return {"success": True, "message": "文件删除成功"}
    except Exception as exc:
        raise _translate_upload_error(exc) from exc


__all__ = ["router"]
