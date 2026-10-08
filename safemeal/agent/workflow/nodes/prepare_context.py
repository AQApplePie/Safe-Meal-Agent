"""在解析本轮约束前统一准备历史、记忆和活动菜单上下文。"""

import asyncio

from safemeal.agent.contracts.workflow.models import WorkflowState
from safemeal.agent.understanding.request_understanding import (
    RequestUnderstandingService,
)
from safemeal.agent.context.menu_planning import (
    resolve_active_menu_recipe_reference,
)
from safemeal.agent.workflow.streaming import emit_workflow_progress
from safemeal.agent.workflow.context.builder import AgentContextBuilder
from safemeal.shared.contracts.request_frame import (
    CategoryQuota,
    MenuPlanningRequirements,
    RequestTask,
)


class PrepareContextNode:
    def __init__(self, builder: AgentContextBuilder):
        self.builder = builder

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        await emit_workflow_progress(
            "prepare_context", "正在加载历史与饮食记忆并整理上下文"
        )
        request = state["request"]
        frame = state.get("request_frame")
        if frame is None:
            # 仅为节点独立测试保留；正式 Workflow 一定由上游提供 RequestFrame。
            frame = RequestUnderstandingService().understand(request.message)
        safety_tasks = {
            "recipe_recommendation",
            "recipe_generation",
            "replace",
            "food_safety",
        }
        needs = set(frame.context_needs)
        if (
            frame.primary_task in safety_tasks
            or frame.understanding_status != "accepted"
        ):
            needs.update({"allergies", "dietary_restrictions"})
        frame = frame.model_copy(update={"context_needs": tuple(sorted(needs))})
        preloaded_history = state.get("recent_history")
        preloaded_active_menu = state.get("active_menu")
        if preloaded_history is None:
            fallback_history = request.history or (
                request.context.conversation_history if request.context else []
            )
            if hasattr(self.builder, "load_context_sources"):
                preloaded_history, loaded_active_menu = self.builder.load_context_sources(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    source_message_id=request.source_message_id,
                    fallback=fallback_history,
                )
                if preloaded_active_menu is None:
                    preloaded_active_menu = loaded_active_menu
            else:
                preloaded_history = list(fallback_history)
        context = await asyncio.to_thread(
            self.builder.build_chat_context,
            user_id=request.user_id,
            message=request.message,
            session_id=request.session_id,
            conversation_history=request.history
            or (request.context.conversation_history if request.context else []),
            source_message_id=request.source_message_id,
            use_user_memory=request.use_user_memory,
            request_frame=frame,
            preloaded_history=preloaded_history,
            preloaded_active_menu=preloaded_active_menu,
        )
        active_menu = context.context_metadata.get("active_menu")
        if frame.primary_task == "recipe_detail" and isinstance(active_menu, dict):
            # “第二道荤菜”优先从结构化活动菜单解析，不依赖助手自然语言文本。
            referenced_name = resolve_active_menu_recipe_reference(
                request.message, active_menu
            )
            if referenced_name is not None:
                frame = frame.model_copy(
                    update={
                        "target": frame.target.model_copy(
                            update={"recipe_name": referenced_name}
                        ),
                        "context_relation": "reference",
                        "exact_match_required": True,
                    }
                )
                context.request_frame = frame
        if (
            frame.context_relation == "modification"
            and frame.operation == "replace"
            and frame.target.menu_category is not None
            and isinstance(active_menu, dict)
        ):
            plan = active_menu.get("plan")
            progress = active_menu.get("progress")
            category = frame.target.menu_category
            if isinstance(plan, dict) and isinstance(progress, dict):
                required = plan.get("required")
                inherited = (
                    required.get(category) if isinstance(required, dict) else None
                )
                count = frame.recommendation_count or inherited
                if isinstance(count, int) and count > 0:
                    previous = [
                        item
                        for item in progress.get("selected_recipes", [])
                        if isinstance(item, dict)
                        and item.get("assigned_category") == category
                    ]
                    # 替换分类时同时排除保留分类中的菜，防止合并后破坏全菜单去重约束。
                    preserved = [
                        item
                        for item in progress.get("selected_recipes", [])
                        if isinstance(item, dict)
                        and item.get("assigned_category") != category
                    ]
                    excluded = [*previous, *preserved]
                    frame = frame.model_copy(
                        update={
                            "tasks": (RequestTask(kind="menu_planning"),),
                            "recommendation_count": count,
                            "scenario": plan.get("scenario"),
                            "menu_planning": MenuPlanningRequirements(
                                category_quotas=(
                                    CategoryQuota(category=category, count=count),
                                )
                            ),
                        }
                    )
                    context.request_frame = frame
                    context.context_metadata["menu_modification"] = {
                        "operation": "replace",
                        "target_category": category,
                        "requested_count": count,
                        "exclude_recipe_ids": [
                            item["recipe_id"]
                            for item in excluded
                            if item.get("recipe_id") is not None
                        ],
                        "exclude_recipe_names": [
                            item["name"]
                            for item in excluded
                            if isinstance(item.get("name"), str)
                        ],
                        "replaced_recipe_ids": [
                            item["recipe_id"]
                            for item in previous
                            if item.get("recipe_id") is not None
                        ],
                        "replaced_recipe_names": [
                            item["name"]
                            for item in previous
                            if isinstance(item.get("name"), str)
                        ],
                    }
        if request.context:
            supplied = request.context.model_copy(deep=True)
            context.observations.extend(supplied.observations)
            context.user_memories.extend(supplied.user_memories)
            context.episodic_memories.extend(supplied.episodic_memories)
            context.context_metadata = {
                **supplied.context_metadata,
                **context.context_metadata,
            }
            context.user_profile = supplied.user_profile
            context.dietary_constraints = supplied.dietary_constraints
            context.requirements = supplied.requirements
        context.context_metadata.update(
            {
                "request_understanding_backend": frame.backend,
                "request_understanding_confidence": frame.confidence,
                "understanding_status": frame.understanding_status,
                "request_tasks": [task.kind for task in frame.tasks],
                "context_needs": list(frame.context_needs),
                "fallback_used": frame.fallback_used,
            }
        )
        return {"context": context, "request_frame": frame}
