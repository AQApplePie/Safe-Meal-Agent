"""协调单轮聊天消息的事务性持久化。"""

from __future__ import annotations
from safemeal.modules.conversation.contracts.chat.turn import ChatTurnStart

from datetime import datetime, timezone
from typing import Iterable, Optional
from uuid import uuid4

from safemeal.modules.conversation.contracts.chat.messages import (
    ChatMessageCreate,
    ChatMessageUpdate,
    ChatSessionCreate,
)
from safemeal.modules.conversation.ports.chat_repository import (
    ChatMessageRecord,
    ChatSessionRecord,
    ChatUnitOfWork,
    ChatUnitOfWorkFactory,
)
from safemeal.modules.conversation.application.chat_exceptions import (
    ChatSessionNotFoundError,
    ChatTurnConflictError,
)
from safemeal.shared.types import JsonObject, JsonValue, to_json_value


_GENERIC_AGENT_ERROR = "抱歉，处理您的请求时出现了错误。请稍后重试。"


# 类说明（业务或基础设施实现类）：ChatTurnPersistence
# 作用：实现聊天轮次及审批持久化服务，封装该组件的业务处理与依赖协作。
class ChatTurnPersistence:
    # 方法说明：__init__
    # 作用：初始化聊天轮次及审批持久化服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   uow_factory（ChatUnitOfWorkFactory）：创建事务工作单元的工厂。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        uow_factory: ChatUnitOfWorkFactory,
    ) -> None:
        # 实例属性说明：_uow_factory
        # 作用：创建事务工作单元的工厂。
        self._uow_factory = uow_factory

    # 方法说明：start_turn
    # 作用：保存用户消息并取得聊天轮次执行权，处理请求标识重复。
    # 入参：
    #   session_id（Optional[str]）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   message（str）：本轮用户消息或问题文本。
    #   request_id（Optional[str]）：用于请求关联或聊天防重的请求标识；默认值为 None。
    # 出参：ChatTurnStart；聊天轮次启动结果。
    def start_turn(
        self,
        session_id: Optional[str],
        user_id: str,
        message: str,
        *,
        request_id: Optional[str] = None,
    ) -> ChatTurnStart:

        with self._uow_factory() as uow:
            if session_id is None:
                session_id = str(uuid4())
                uow.sessions.create(
                    ChatSessionCreate(
                        id=session_id,
                        user_id=user_id,
                        title=f"Chat {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
                    )
                )
            elif uow.sessions.get_active(session_id, user_id=user_id) is None:
                raise ChatSessionNotFoundError()

            first_order = uow.messages.next_order(session_id, user_id=user_id)
            if first_order is None:
                raise ChatSessionNotFoundError()
            created = uow.messages.create(
                ChatMessageCreate(
                    session_id=session_id,
                    message_type="user_query",
                    content=message,
                    order_index=first_order,
                    client_request_id=request_id,
                    turn_status="processing",
                )
            )
            uow.commit()

        return ChatTurnStart(
            session_id=session_id,
            user_message_id=created.id,
            response_order_index=first_order + 1,
        )

    # 方法说明：save_agent_response
    # 作用：将安全复核后的 Agent 回答持久化并完成当前轮次。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   user_message_id（int）：本轮用户消息标识。
    #   response_order_index（int）：助手响应在会话中的顺序号。
    #   response（str）：底层客户端响应或最终业务响应。
    #   route（Optional[str]）：HTTP 路由模板或业务路由标识；默认值为 None。
    #   route_logic（Optional[str]）：决定执行分支的路由函数；默认值为 None。
    #   sources（Iterable[object]）：当前答案或上下文的证据来源集合；默认值为 ()。
    #   metadata（Optional[JsonObject]）：文档、消息或证据的来源与辅助元数据；默认值为 None。
    # 出参：str；新保存助手消息的标识字符串。
    def save_agent_response(
        self,
        *,
        session_id: str,
        user_id: str,
        user_message_id: int,
        response_order_index: int,
        response: str,
        route: Optional[str] = None,
        route_logic: Optional[str] = None,
        sources: Iterable[object] = (),
        metadata: Optional[JsonObject] = None,
    ) -> str:
        response_metadata = {
            **(metadata or {}),
            "route": route,
            "route_logic": route_logic,
            "sources": [self._json_value(source) for source in sources],
        }
        with self._uow_factory() as uow:
            self._require_owned_session(uow, session_id, user_id=user_id)
            user_message = self._require_user_message(
                uow, user_message_id, session_id=session_id, user_id=user_id
            )
            created = uow.messages.create(
                ChatMessageCreate(
                    session_id=session_id,
                    message_type="agent_response",
                    content=response,
                    message_metadata=response_metadata,
                    order_index=response_order_index,
                    reply_to_message_id=user_message_id,
                )
            )
            uow.messages.update(
                user_message.id, ChatMessageUpdate(turn_status="completed")
            )
            uow.sessions.touch(session_id, user_id=user_id)
            uow.commit()
        return str(created.id)

    # 方法说明：claim_approval
    # 作用：按消息、审批标识和待处理状态原子认领审批执行权。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   message_id（int）：聊天消息标识。
    #   approval_id（str）：绑定当前待审批操作的审批标识。
    #   approved（bool）：用户是否明确同意执行当前待审批操作。
    # 出参：JsonObject；JSON 字段映射。
    def claim_approval(
        self,
        *,
        session_id: str,
        user_id: str,
        message_id: int,
        approval_id: str,
        approved: bool,
    ) -> JsonObject:
        with self._uow_factory() as uow:
            self._require_owned_session(uow, session_id, user_id=user_id)
            message = uow.messages.get(message_id, user_id=user_id)
            if message is None or message.session_id != session_id:
                raise ChatSessionNotFoundError()
            metadata = dict(message.message_metadata or {})
            if (
                message.message_type != "agent_response"
                or message.turn_status is not None
                or metadata.get("approval_required") is not True
                or metadata.get("approval_id") != approval_id
            ):
                raise ChatTurnConflictError(
                    "Approval is stale, already submitted or unavailable"
                )
            history = metadata.get("approval_history")
            metadata["approval_history"] = [
                *(history if isinstance(history, list) else []),
                {
                    "approval_id": approval_id,
                    "approved": approved,
                    "calls": metadata.get("pending_calls", []),
                    "decided_at": datetime.now(timezone.utc).isoformat(),
                },
            ]
            metadata["approval_state"] = "processing"
            if not uow.messages.claim_approval(
                message_id, approval_id=approval_id, metadata=metadata
            ):
                raise ChatTurnConflictError(
                    "Approval is stale, already submitted or unavailable"
                )
            uow.commit()
            return metadata

    # 方法说明：finish_approval
    # 作用：将审批执行结果和最终响应写回被认领的原消息。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   message_id（int）：聊天消息标识。
    #   content（str）：当前文件、消息或证据的正文内容。
    #   metadata（JsonObject）：文档、消息或证据的来源与辅助元数据。
    #   failed（bool）：本次操作是否失败；默认值为 False。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def finish_approval(
        self,
        *,
        session_id: str,
        user_id: str,
        message_id: int,
        content: str,
        metadata: JsonObject,
        failed: bool = False,
    ) -> None:
        with self._uow_factory() as uow:
            self._require_owned_session(uow, session_id, user_id=user_id)
            message = uow.messages.get(message_id, user_id=user_id)
            if (
                message is None
                or message.session_id != session_id
                or message.turn_status != "processing"
            ):
                raise ChatTurnConflictError("Approval claim is missing")
            pending = metadata.get("approval_required") is True
            uow.messages.update(
                message_id,
                ChatMessageUpdate(
                    content=content,
                    message_metadata=metadata,
                    turn_status="failed"
                    if failed
                    else (None if pending else "completed"),
                ),
            )
            uow.sessions.touch(session_id, user_id=user_id)
            uow.commit()

    # 方法说明：save_agent_error
    # 作用：将 Agent 失败信息关联并持久化到当前聊天轮次。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   user_message_id（int）：本轮用户消息标识。
    #   response_order_index（int）：助手响应在会话中的顺序号。
    #   error_code（Optional[str]）：对外稳定的错误码。
    # 出参：str；新保存助手消息的标识字符串。
    def save_agent_error(
        self,
        *,
        session_id: str,
        user_id: str,
        user_message_id: int,
        response_order_index: int,
        error_code: Optional[str],
    ) -> str:
        with self._uow_factory() as uow:
            self._require_owned_session(uow, session_id, user_id=user_id)
            user_message = self._require_user_message(
                uow, user_message_id, session_id=session_id, user_id=user_id
            )
            created = uow.messages.create(
                ChatMessageCreate(
                    session_id=session_id,
                    message_type="error",
                    content=_GENERIC_AGENT_ERROR,
                    message_metadata={
                        "error_code": error_code or "agent_execution_failed"
                    },
                    order_index=response_order_index,
                    reply_to_message_id=user_message_id,
                )
            )
            uow.messages.update(
                user_message.id, ChatMessageUpdate(turn_status="failed")
            )
            uow.sessions.touch(session_id, user_id=user_id)
            uow.commit()
        return str(created.id)

    # 方法说明：mark_turn_failed
    # 作用：将指定聊天轮次标记为失败并记录错误信息。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   user_message_id（int）：本轮用户消息标识。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def mark_turn_failed(
        self,
        *,
        session_id: str,
        user_id: str,
        user_message_id: int,
    ) -> None:
        with self._uow_factory() as uow:
            self._require_owned_session(uow, session_id, user_id=user_id)
            user_message = self._require_user_message(
                uow, user_message_id, session_id=session_id, user_id=user_id
            )
            uow.messages.update(
                user_message.id, ChatMessageUpdate(turn_status="failed")
            )
            uow.commit()

    # 方法说明：_require_owned_session
    # 作用：校验会话存在且归属于当前用户。
    # 入参：
    #   uow（ChatUnitOfWork）：当前事务工作单元。
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：ChatSessionRecord；聊天会话仓储记录接口。
    @staticmethod
    def _require_owned_session(
        uow: ChatUnitOfWork,
        session_id: str,
        *,
        user_id: str,
    ) -> ChatSessionRecord:
        session = uow.sessions.get_active(session_id, user_id=user_id)
        if session is None:
            raise ChatSessionNotFoundError()
        return session

    # 方法说明：_require_user_message
    # 作用：读取并验证当前用户消息，确保可以关联助手回复。
    # 入参：
    #   uow（ChatUnitOfWork）：当前事务工作单元。
    #   message_id（int）：聊天消息标识。
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：ChatMessageRecord；聊天消息仓储记录接口。
    @staticmethod
    def _require_user_message(
        uow: ChatUnitOfWork,
        message_id: int,
        *,
        session_id: str,
        user_id: str,
    ) -> ChatMessageRecord:
        message = uow.messages.get(message_id, user_id=user_id)
        if (
            message is None
            or message.session_id != session_id
            or message.message_type != "user_query"
        ):
            raise ChatTurnConflictError("user turn is missing")
        return message

    # 方法说明：_json_value
    # 作用：将持久化元数据转换为稳定的 JSON 兼容值。
    # 入参：
    #   value（object）：当前待转换或校验的值。
    # 出参：JsonValue；JSON 兼容数据。
    @staticmethod
    def _json_value(value: object) -> JsonValue:
        return to_json_value(value)


__all__ = ["ChatTurnPersistence", "ChatTurnStart"]
