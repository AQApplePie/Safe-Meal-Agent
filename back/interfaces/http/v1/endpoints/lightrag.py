"""LightRAG HTTP API."""

import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from SafeMealAgent.back.application.errors import ApplicationError
from SafeMealAgent.back.application.use_cases.knowledge.lightrag_service import (
    LightRAGApplicationService,
)
from SafeMealAgent.back.interfaces.http.dependencies import get_lightrag_application_service
from SafeMealAgent.back.interfaces.http.models.lightrag import (
    LightRAGInsertRequest,
    LightRAGInsertResponse,
    LightRAGQueryRequest,
    LightRAGQueryResponse,
)
from SafeMealAgent.back.infrastructure.operations.logging import get_logger
from SafeMealAgent.back.shared.types import JsonObject

logger = get_logger(service="lightrag-api")

router = APIRouter(prefix="/lightrag", tags=["LightRAG"])


def _provider_error(detail: str = "LightRAG operation failed") -> HTTPException:
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)


@router.post("/query", response_model=LightRAGQueryResponse)
async def query_lightrag(
    request: LightRAGQueryRequest,
    service: LightRAGApplicationService = Depends(get_lightrag_application_service),
) -> LightRAGQueryResponse:
    if request.stream:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="此接口不支持流式响应，请使用 /query-stream",
        )
    try:
        result = await service.query(
            query=request.query,
            mode=request.mode,
            top_k=request.top_k,
        )
        return LightRAGQueryResponse(
            query=result.query,
            response=result.response,
            mode=result.mode,
            metadata=result.metadata,
        )
    except ApplicationError as exc:
        logger.warning("LightRAG query failed: {}", exc)
        raise _provider_error("LightRAG query failed") from exc
    except Exception as exc:
        logger.exception("Unexpected LightRAG query failure")
        raise _provider_error("LightRAG query failed") from exc


@router.post("/query-stream")
async def query_lightrag_stream(
    request: LightRAGQueryRequest,
    http_request: Request,
    service: LightRAGApplicationService = Depends(get_lightrag_application_service),
) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        try:
            async for chunk in service.query_stream(
                query=request.query,
                mode=request.mode,
                top_k=request.top_k,
            ):
                if await http_request.is_disconnected():
                    return
                yield "event: chunk\n" + f"data: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
        except ApplicationError as exc:
            logger.warning("LightRAG stream failed: {}", exc)
            yield 'event: error\ndata: {"message":"LightRAG stream failed"}\n\n'
        except Exception:
            logger.exception("Unexpected LightRAG stream failure")
            yield 'event: error\ndata: {"message":"LightRAG stream failed"}\n\n'
        finally:
            if not await http_request.is_disconnected():
                yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/insert", response_model=LightRAGInsertResponse)
async def insert_documents(
    request: LightRAGInsertRequest,
    service: LightRAGApplicationService = Depends(get_lightrag_application_service),
) -> LightRAGInsertResponse:
    try:
        result = await service.insert_documents(request.documents)
        return LightRAGInsertResponse(**result.model_dump())
    except ApplicationError as exc:
        logger.warning("LightRAG insert failed: {}", exc)
        raise _provider_error("LightRAG insert failed") from exc
    except Exception as exc:
        logger.exception("Unexpected LightRAG insert failure")
        raise _provider_error("LightRAG insert failed") from exc


@router.get("/stats")
async def get_index_stats(
    service: LightRAGApplicationService = Depends(get_lightrag_application_service),
) -> JsonObject:
    try:
        return service.get_index_stats()
    except ApplicationError as exc:
        logger.warning("LightRAG stats failed: {}", exc)
        raise _provider_error("LightRAG stats failed") from exc
    except Exception as exc:
        logger.exception("Unexpected LightRAG stats failure")
        raise _provider_error("LightRAG stats failed") from exc
