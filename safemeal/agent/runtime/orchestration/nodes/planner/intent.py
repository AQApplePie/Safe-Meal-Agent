"""把规范化请求契约转换为 Agent 内部任务类型。"""

import asyncio
import re
from safemeal.agent.contracts.intent import IntentDecision
from safemeal.agent.contracts.context import AgentContext
from safemeal.agent.runtime.model import IntentClassifier
from safemeal.modules.conversation.application.memory.memory_extraction import UserMemoryExtractor


def intent_from_request_frame(context: AgentContext) -> IntentDecision | None:
    """优先使用 Workflow 已确认的请求事实，不在 Agent 内重复理解原文。"""

    frame = context.request_frame
    # 显式菜单配额属于确定性事实，即使小模型降级也必须进入菜单规划分支。
    if (
        frame is not None
        and frame.primary_task == "menu_planning"
        and frame.menu_planning is not None
    ):
        return IntentDecision(kind="menu_planning", reason="explicit_menu_quotas")
    if (
        frame is not None
        and frame.primary_task == "menu_planning"
        and frame.menu_planning is None
        and frame.canonical
    ):
        # 未提供分类配额的配餐请求沿用普通推荐，不启动配额完成度计算。
        return IntentDecision(kind="recommend", reason="adaptive_meal_request")
    if (
        frame is not None
        and frame.primary_task == "recipe_detail"
        and frame.target.recipe_name
        and frame.requested_fields
        and frame.exact_match_required
    ):
        # 规则降级结果只要菜名和字段完整，就可以直接执行精确查询。
        return IntentDecision(kind="recipe_detail", reason="complete_detail_contract")
    if frame is None or not frame.canonical or not frame.tasks:
        return None
    mapping = {
        "recipe_recommendation": "recommend",
        "recipe_generation": "generate",
        "nutrition_query": "knowledge",
        "food_safety": "knowledge",
    }
    return IntentDecision(
        kind=mapping.get(frame.primary_task, frame.primary_task),
        clarification=frame.clarification_question or "",
    )


async def resolve_agent_intent(
    message: str, context: AgentContext, classifier: IntentClassifier | None = None
) -> IntentDecision:
    """解析 Agent 任务；原文规则仅服务于没有 RequestFrame 的兼容调用。"""

    message = message.strip()
    framed = intent_from_request_frame(context)
    if framed is not None:
        return framed
    if UserMemoryExtractor().extract_dietary_retractions(message):
        decision = IntentDecision(
            kind="clarify",
            clarification="这涉及修改已保存的过敏或忌口档案。请在记忆管理中明确修改对应记录；本轮继续保留已有约束。",
        )
    elif re.search(r"换一[道个]|换成|替[换代]|不要上一", message):
        decision = (
            IntentDecision(kind="replace")
            if context.conversation_history or re.search(r"替[换代].+|换成.+", message)
            else IntentDecision(
                kind="clarify", clarification="你想替换哪道菜或哪种食材？"
            )
        )
    elif any(x in message for x in ("生成", "设计", "创作", "制定", "原创")) and any(
        x in message for x in ("菜", "食谱", "配方", "餐")
    ):
        decision = IntentDecision(kind="generate")
    elif any(
        x in message
        for x in (
            "推荐",
            "吃什么",
            "吃点",
            "晚餐",
            "早餐",
            "午餐",
            "晚饭",
            "做饭",
            "做菜",
        )
    ):
        decision = IntentDecision(kind="recommend")
    elif any(x in message for x in ("怎么做", "做法", "步骤", "菜谱详情")):
        decision = IntentDecision(kind="recipe_detail")
    elif any(
        x in message for x in ("记住", "我喜欢", "我不喜欢", "我对", "我过敏")
    ) and not any(x in message for x in ("为什么", "怎么", "吗", "？", "?")):
        decision = IntentDecision(kind="memory")
    elif (
        any(
            x in message
            for x in (
                "食材",
                "菜",
                "食谱",
                "烹饪",
                "过敏",
                "营养",
                "食物",
                "资料",
                "知识库",
                "蒸",
                "煮",
                "炒",
            )
        )
        or context.conversation_history
    ):
        decision = IntentDecision(kind="knowledge")
    else:
        decision = IntentDecision(kind="out_of_scope")
    if classifier is not None and decision.kind in {"knowledge", "out_of_scope"}:
        try:
            decision = await asyncio.wait_for(
                classifier.classify_intent(message, context), timeout=15
            )
        except Exception:
            decision = IntentDecision(kind="clarify")
        if decision.kind == "clarify":
            decision.clarification = "请补充你想查询的菜名、食材或本轮用餐要求。"
    return decision
