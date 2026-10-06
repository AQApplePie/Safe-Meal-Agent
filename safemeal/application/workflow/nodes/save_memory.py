"""实现聊天工作流中的对应职责。"""

import asyncio
import re
from safemeal.application.contracts.workflow.models import WorkflowState
from safemeal.application.service.memory.user_memory_service import UserMemoryService


from safemeal.application.service.memory.memory_extraction import UserMemoryExtractor


class SaveMemoryNode:
    def __init__(self, memory_service: UserMemoryService):
        self.memory_service = memory_service

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        request = state["request"]
        message = request.message
        intent = state["result"].intent
        if request.use_user_memory:
            for episode in state["context"].episodic_memories:
                if episode.get("relevance_basis") != "token_budget_compaction":
                    continue
                try:
                    await asyncio.to_thread(
                        self.memory_service.remember_episode,
                        user_id=request.user_id,
                        session_id=request.session_id,
                        summary=str(episode.get("summary") or ""),
                        message_count=int(episode.get("message_count") or 0),
                    )
                except Exception:
                    state["result"].metadata["episodic_memory_saved"] = False

        frame = state.get("request_frame") or state["context"].request_frame
        personal = bool(frame and frame.memory_updates) or bool(
            re.search(
                r"我(?:本人)?(?:对|喜欢|爱吃|不喜欢|不爱吃|讨厌|过敏|不能吃|不吃)|记住.{0,8}我",
                message,
            )
        )
        temporary = bool(
            re.search(
                r"今天|这次|今晚|本次|朋友|家人|孩子|假如|假设|如果|比如|例如|[“‘]",
                message,
            )
        )
        participant_meal = bool(
            frame
            and frame.primary_task == "menu_planning"
            and any(owner in {"spouse", "child"} for owner in frame.participants)
        )
        if (
            request.use_user_memory
            and personal
            and not temporary
            and not participant_meal
            and not UserMemoryExtractor().extract_dietary_retractions(message)
            and (intent is None or intent.kind != "clarify")
        ):
            try:
                saved = await asyncio.to_thread(
                    self.memory_service.remember_from_message,
                    user_id=request.user_id,
                    message=message,
                    source_session_id=request.session_id,
                    source_message_id=request.source_message_id,
                )
                result = state["result"].model_copy(deep=True)
                result.metadata["memory_saved"] = bool(saved)
                return {"result": result}
            except Exception:
                result = state["result"].model_copy(deep=True)
                result.metadata["memory_saved"] = False
                return {"result": result}
        return {}
