"""Bounded culinary intent routing, with explicit clarification branches."""

from safemeal.application.observability.streaming import emit_workflow_progress
import re
import asyncio
from safemeal.application.ports.llm.intent_classifier import IntentClassifier
from safemeal.application.contracts.workflow.models import IntentDecision, WorkflowState
from safemeal.modules.user_memory.memory_extraction import UserMemoryExtractor


async def identify_intent(state: WorkflowState) -> WorkflowState:
    await emit_workflow_progress("identify_intent", "正在识别你的需求")
    message = state["request"].message.strip()
    context = state["context"].model_copy(deep=True)
    if state["request"].resume_approved is not None and context.intent:
        return {
            "intent": IntentDecision.model_validate({"kind": context.intent}),
            "context": context,
        }
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
    context.intent = decision.kind
    return {"intent": decision, "context": context}


class IdentifyIntentNode:
    """Use local guards for clear intents, structured classification for ambiguity."""

    def __init__(self, classifier: IntentClassifier | None = None):
        self.classifier = classifier

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        update = await identify_intent(state)
        decision = update["intent"]
        context = update["context"]
        if (
            self.classifier is not None
            and decision.kind in {"knowledge", "out_of_scope"}
            and state["request"].resume_approved is None
        ):
            try:
                decision = await asyncio.wait_for(
                    self.classifier.classify_intent(state["request"].message, context),
                    timeout=15,
                )
                if decision.kind == "clarify":
                    decision.clarification = (
                        "请补充你想查询的菜名、食材或本轮用餐要求。"
                    )
            except Exception:
                decision = IntentDecision(
                    kind="clarify",
                    clarification="请说明你想查询哪道菜、推荐一餐，还是了解食材或烹饪知识。",
                )
        if decision.kind == "clarify" and not decision.clarification:
            decision.clarification = "请补充你想查询的菜名、食材或本轮用餐要求。"
        context.intent = decision.kind
        return {"intent": decision, "context": context}
