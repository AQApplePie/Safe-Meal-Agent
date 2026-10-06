"""文件上传 HTTP 路由。

Router 只做协议转换和状态码处理，文件系统业务由 FileUploadService 统一完成。
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from loguru import logger

from safemeal.application.service.upload.file_upload_service import (
    UploadNotFoundError,
    FileUploadService,
    UploadSizeLimitError,
    InvalidUploadError,
)
from safemeal.interfaces.http.dependencies import (
    get_file_upload_service,
    get_uploaded_document_ingestion_service,
)
from safemeal.application.service.knowledge.chunking import ChunkStrategyName
from safemeal.application.ports import DocumentParseError
from safemeal.application.service.upload.uploaded_document_ingestion_service import (
    UploadedDocumentIngestionService,
)
from safemeal.shared.types import JsonObject
from safemeal.application.service.composition.application_container import (
    ApplicationContainer,
)
from safemeal.interfaces.http.dependencies import get_container
from safemeal.interfaces.http.authentication import Principal, get_current_principal
from safemeal.application.contracts.upload.ingestion import IngestionJob

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


@router.post("/files")
async def upload_and_ingest_file(
    file: UploadFile = File(...),
    chunk_strategy: ChunkStrategyName = Form(default="auto"),
    file_upload_service: FileUploadService = Depends(get_file_upload_service),
    ingestion: UploadedDocumentIngestionService = Depends(
        get_uploaded_document_ingestion_service
    ),
    principal: Principal = Depends(get_current_principal),
) -> JsonObject:

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


@router.post("/files/async", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_uploaded_document(
    file: UploadFile = File(...),
    chunk_strategy: ChunkStrategyName = Form(default="auto"),
    file_upload_service: FileUploadService = Depends(get_file_upload_service),
    container: ApplicationContainer = Depends(get_container),
    principal: Principal = Depends(get_current_principal),
) -> JsonObject:

    if container.ingestion_queue is None:
        raise HTTPException(status_code=503, detail="后台摄取队列未配置")
    try:
        content = await _read_upload(file, file_upload_service)
    except UploadSizeLimitError as exc:
        raise _translate_upload_error(exc) from exc
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


@router.get("/files")
def list_files(
    principal: Principal = Depends(get_current_principal),
    files: FileUploadService = Depends(get_file_upload_service),
):
    return files.list_documents(principal.tenant_id)


@router.get("/files/{file_id}")
def get_file(
    file_id: str,
    principal: Principal = Depends(get_current_principal),
    files: FileUploadService = Depends(get_file_upload_service),
):
    try:
        return files.get_document(file_id, principal.tenant_id)
    except UploadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/files/{file_id}/content")
def download_file(
    file_id: str,
    principal: Principal = Depends(get_current_principal),
    files: FileUploadService = Depends(get_file_upload_service),
):
    try:
        record = files.get_document(file_id, principal.tenant_id)
        return FileResponse(
            files.resolve(record.file.filename), filename=record.file.original_name
        )
    except UploadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: str,
    principal: Principal = Depends(get_current_principal),
    ingestion: UploadedDocumentIngestionService = Depends(
        get_uploaded_document_ingestion_service
    ),
):
    try:
        await ingestion.delete(file_id=file_id, tenant_id=principal.tenant_id)
        return {"success": True}
    except UploadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


__all__ = ["router"]
