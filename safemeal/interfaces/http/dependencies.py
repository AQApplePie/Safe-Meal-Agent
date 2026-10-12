"""HTTP 依赖装配。

本模块是 FastAPI 接口层的依赖入口，只负责把请求绑定到组合根或服务客户端，
不承载业务规则。
"""

from fastapi import Depends
from safemeal.interfaces.http.platform_dependencies import (
    get_auth_service as get_auth_service,
    get_container as get_container,
    get_history_service as get_history_service,
    get_interaction_service as get_interaction_service,
    get_ranking_service as get_ranking_service,
    get_recipe_browse_service as get_recipe_browse_service,
)

from safemeal.agent.workflow.runner import ChatWorkflow
from safemeal.modules.conversation.application.chat_session_service import (
    ChatSessionService,
)
from safemeal.agent.gateway.chat_turn_service import ChatTurnService
from safemeal.modules.conversation.application.memory.user_memory_service import (
    UserMemoryService,
)
from safemeal.modules.knowledge.application.upload.file_upload_service import (
    FileUploadService,
)
from safemeal.modules.knowledge.application.upload.uploaded_document_ingestion_service import (
    UploadedDocumentIngestionService,
)
from safemeal.bootstrap.composition.application_container import (
    ApplicationContainer,
)


# 方法说明：get_chat_session_service
# 作用：提供会话及消息管理业务服务。
# 入参：
#   container（ApplicationContainer）：当前应用的依赖容器；由 FastAPI 依赖注入。
# 出参：ChatSessionService；聊天会话与历史消息管理服务。
def get_chat_session_service(
    container: ApplicationContainer = Depends(get_container),
) -> ChatSessionService:
    return container.get_chat_session_service()


# 方法说明：get_user_memory_service
# 作用：返回本地用户长期记忆用例，供主 API 的 memories 路由使用。
# 入参：
#   container（ApplicationContainer）：当前应用的依赖容器；由 FastAPI 依赖注入。
# 出参：UserMemoryService；长期记忆管理与上下文服务。
def get_user_memory_service(
    container: ApplicationContainer = Depends(get_container),
) -> UserMemoryService:
    """返回本地用户长期记忆用例，供主 API 的 memories 路由使用。"""

    return container.get_user_memory_service()


# 方法说明：get_chat_turn_service
# 作用：装配一轮 Chat 用例。
# 入参：
#   container（ApplicationContainer）：当前应用的依赖容器；由 FastAPI 依赖注入。
# 出参：ChatTurnService；单轮聊天编排服务。
def get_chat_turn_service(
    container: ApplicationContainer = Depends(get_container),
) -> ChatTurnService:
    """装配一轮 Chat 用例。

    HTTP Router 不再直接串联 Agent、Memory、Persistence，而是只依赖该用例服务。
    """

    return container.get_chat_turn_service()


# 方法说明：get_chat_workflow
# 作用：提供统一 Workflow 运行入口。
# 入参：
#   container（ApplicationContainer）：当前应用的依赖容器；由 FastAPI 依赖注入。
# 出参：ChatWorkflow；聊天 Workflow 执行入口。
def get_chat_workflow(
    container: ApplicationContainer = Depends(get_container),
) -> ChatWorkflow:
    """提供统一 Workflow 运行入口。"""

    return container.get_chat_workflow()


# 方法说明：get_file_upload_service
# 作用：提供文件校验与保存业务服务。
# 入参：
#   container（ApplicationContainer）：当前应用的依赖容器；由 FastAPI 依赖注入。
# 出参：FileUploadService；文件上传校验与保存服务。
def get_file_upload_service(
    container: ApplicationContainer = Depends(get_container),
) -> FileUploadService:
    return container.file_upload_service


# 方法说明：get_uploaded_document_ingestion_service
# 作用：提供上传文档的解析与入库服务。
# 入参：
#   container（ApplicationContainer）：当前应用的依赖容器；由 FastAPI 依赖注入。
# 出参：UploadedDocumentIngestionService；上传文档解析分块与索引服务。
async def get_uploaded_document_ingestion_service(
    container: ApplicationContainer = Depends(get_container),
) -> UploadedDocumentIngestionService:
    return await container.get_uploaded_document_ingestion_service()
