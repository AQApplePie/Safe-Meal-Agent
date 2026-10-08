"""HTTP 依赖装配。

本模块是 FastAPI 接口层的依赖入口，只负责把请求绑定到组合根或服务客户端，
不承载业务规则。
"""

from fastapi import Depends, Request

from safemeal.agent.workflow.runner import ChatWorkflow
from safemeal.modules.conversation.application.chat_session_service import (
    ChatSessionService,
)
from safemeal.agent.gateway.chat_turn_service import ChatTurnService
from safemeal.modules.conversation.application.memory.user_memory_service import UserMemoryService
from safemeal.modules.identity.application import AuthService
from safemeal.modules.knowledge.application.upload.file_upload_service import FileUploadService
from safemeal.modules.knowledge.application.upload.uploaded_document_ingestion_service import (
    UploadedDocumentIngestionService,
)
from safemeal.bootstrap.composition.application_container import (
    ApplicationContainer,
)


def get_container(request: Request) -> ApplicationContainer:

    return request.app.state.container


def get_chat_session_service(
    container: ApplicationContainer = Depends(get_container),
) -> ChatSessionService:
    return container.get_chat_session_service()


def get_user_memory_service(
    container: ApplicationContainer = Depends(get_container),
) -> UserMemoryService:
    """返回本地用户长期记忆用例，供主 API 的 memories 路由使用。"""

    return container.get_user_memory_service()


def get_auth_service(
    container: ApplicationContainer = Depends(get_container),
) -> AuthService:
    return container.get_auth_service()


def get_chat_turn_service(
    container: ApplicationContainer = Depends(get_container),
) -> ChatTurnService:
    """装配一轮 Chat 用例。

    HTTP Router 不再直接串联 Agent、Memory、Persistence，而是只依赖该用例服务。
    """

    return container.get_chat_turn_service()


def get_chat_workflow(
    container: ApplicationContainer = Depends(get_container),
) -> ChatWorkflow:
    """提供统一 Workflow 运行入口。"""

    return container.get_chat_workflow()


def get_file_upload_service(
    container: ApplicationContainer = Depends(get_container),
) -> FileUploadService:
    return container.file_upload_service


async def get_uploaded_document_ingestion_service(
    container: ApplicationContainer = Depends(get_container),
) -> UploadedDocumentIngestionService:
    return await container.get_uploaded_document_ingestion_service()
