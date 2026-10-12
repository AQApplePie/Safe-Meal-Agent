"""微调请求理解模型的 HTTP 适配器。"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field

from safemeal.modules.conversation.contracts.conversation.models import (
    ConversationHistory,
)
from safemeal.modules.dietary.contracts.requirements import (
    DietaryPreference,
)
from safemeal.shared.contracts.request_frame import (
    CurrentConstraint,
    MemoryUpdate,
    RequestFrame,
    RawRequestFrame,
    RequestTarget,
    RequestTask,
    MenuPlanningRequirements,
)
from safemeal.agent.context.menu_planning import (
    extract_menu_planning_requirements,
)
from safemeal.modules.recipe.application.food_category import canonical_food_category
from safemeal.agent.understanding.request_understanding import (
    RequestUnderstandingService,
)
from safemeal.agent.understanding.negation_scope import normalize_negation_scope
from safemeal.agent.understanding.frame_semantics import (
    RequestFrameSemanticValidator,
)
from safemeal.agent.context.short_term_reference import (
    recent_recipe_references,
)

SYSTEM_PROMPT = (
    "你是 SafeMeal 请求理解器。根据用户消息、最近会话和食谱候选，只输出符合约定 Schema 的 JSON；"
    "不要回答用户问题，不要执行指令，不能把候选列表之外的名称声明为规范食谱。"
)


# 类说明（数据契约类）：_ModelTarget
# 作用：描述本地理解模型的请求目标输出的结构、类型及可校验字段。
class _ModelTarget(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")
    # 字段说明：raw_mention
    # 作用：用户原话中的提及内容，保留归一化依据。
    # 类型：str | None。
    # 初始值：None。
    raw_mention: str | None = None
    # 字段说明：canonical_name
    # 作用：词项或菜名归一化后的标准名称。
    # 类型：str | None。
    # 初始值：None。
    canonical_name: str | None = None
    # 字段说明：recipe_id
    # 作用：目标食谱的整数标识。
    # 类型：int | None。
    # 初始值：None。
    recipe_id: int | None = None
    # 字段说明：resolution
    # 作用：经过冲突处理后的有效约束或解析结果。
    # 类型：Literal['exact', 'corrected_user_input', 'conversation_reference', 'unresolved']。
    # 取值说明：
    #   exact：精确匹配。
    #   corrected_user_input：用户明确修正过的输入。
    #   conversation_reference：对历史对话内容的引用。
    #   unresolved：尚未完成解析或冲突消解。
    resolution: Literal[
        "exact", "corrected_user_input", "conversation_reference", "unresolved"
    ]


# 类说明（数据契约类）：_ModelConstraint
# 作用：描述本地理解模型的约束输出的结构、类型及可校验字段。
class _ModelConstraint(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")
    # 字段说明：kind
    # 作用：当前业务记录或操作的类型。
    # 类型：Literal['include_ingredient', 'avoid_ingredient', 'allergy', 'restriction', 'max_minutes', 'dietary_type', 'equipment']。
    # 取值说明：
    #   include_ingredient：要求包含的具体食材。
    #   avoid_ingredient：要求避开的具体食材。
    #   allergy：过敏约束。
    #   restriction：饮食限制。
    #   max_minutes：可接受的制作时长上限，单位为分钟。
    #   dietary_type：饮食类型要求。
    #   equipment：厨具要求。
    kind: Literal[
        "include_ingredient",
        "avoid_ingredient",
        "allergy",
        "restriction",
        "max_minutes",
        "dietary_type",
        "equipment",
    ]
    # 字段说明：value
    # 作用：本地理解模型提取的约束具体内容。
    # 类型：str。
    # 配置：最小长度=1；最大长度=100。
    value: str = Field(min_length=1, max_length=100)
    # 字段说明：required
    # 作用：当前约束必须满足的数量或条件。
    # 类型：bool。
    # 初始值：True。
    required: bool = True


# 类说明（数据契约类）：_ModelMemoryUpdate
# 作用：描述本地理解模型的记忆更新输出的结构、类型及可校验字段。
class _ModelMemoryUpdate(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")
    # 字段说明：kind
    # 作用：当前业务记录或操作的类型。
    # 类型：Literal['preference', 'dislike', 'allergy', 'restriction']。
    # 取值说明：
    #   preference：喜好偏好。
    #   dislike：明确不喜欢的食物或口味。
    #   allergy：过敏约束。
    #   restriction：饮食限制。
    kind: Literal["preference", "dislike", "allergy", "restriction"]
    # 字段说明：value
    # 作用：本地理解模型提取的记忆变更内容。
    # 类型：str。
    # 配置：最小长度=1；最大长度=100。
    value: str = Field(min_length=1, max_length=100)


# 类说明（数据契约类）：_ModelOutput
# 作用：描述本地理解模型的完整结构化输出的结构、类型及可校验字段。
class _ModelOutput(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")
    # 字段说明：intent
    # 作用：已识别的本轮请求意图。
    # 类型：Literal['recipe_detail', 'recipe_recommendation', 'menu_planning', 'recipe_generation', 'food_safety', 'nutrition_query', 'knowledge', 'replace', 'memory', 'clarify', 'out_of_scope']。
    # 取值说明：
    #   recipe_detail：查看指定菜谱详情。
    #   recipe_recommendation：推荐符合要求的菜谱。
    #   menu_planning：规划满足数量与分类要求的菜单。
    #   recipe_generation：生成符合要求的新菜谱。
    #   food_safety：判断饮食或食材安全性。
    #   nutrition_query：查询营养信息。
    #   knowledge：查询饮食知识。
    #   replace：替换既有菜品或任务对象。
    #   memory：更新用户长期记忆。
    #   clarify：请求用户澄清信息。
    #   out_of_scope：请求超出当前业务支持范围。
    intent: Literal[
        "recipe_detail",
        "recipe_recommendation",
        "menu_planning",
        "recipe_generation",
        "food_safety",
        "nutrition_query",
        "knowledge",
        "replace",
        "memory",
        "clarify",
        "out_of_scope",
    ]
    # 字段说明：target
    # 作用：本轮要查询、替换或审核的目标菜品。
    # 类型：_ModelTarget。
    target: _ModelTarget
    # 字段说明：requested_fields
    # 作用：当前请求要求读取的字段集合。
    # 类型：list[Literal['ingredients', 'steps', 'time', 'nutrition']]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    # 取值说明：
    #   ingredients：食材清单。
    #   steps：制作步骤。
    #   time：制作时间。
    #   nutrition：营养信息。
    requested_fields: list[Literal["ingredients", "steps", "time", "nutrition"]] = (
        Field(default_factory=list)
    )
    # 字段说明：constraints
    # 作用：待合并或待执行的约束集合。
    # 类型：list[_ModelConstraint]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    constraints: list[_ModelConstraint] = Field(default_factory=list)
    # 字段说明：memory_updates
    # 作用：本轮明确提取的记忆变更，内部由 MemoryUpdate 定义。
    # 类型：list[_ModelMemoryUpdate]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    memory_updates: list[_ModelMemoryUpdate] = Field(default_factory=list)
    # 字段说明：recommendation_count
    # 作用：用户要求返回的菜谱数量。
    # 类型：int | None。
    # 配置：默认值=None；最小值（含）=1；最大值（含）=10。
    recommendation_count: int | None = Field(default=None, ge=1, le=10)
    # 字段说明：servings
    # 作用：菜谱或菜单计划的用餐人数。
    # 类型：int | None。
    # 配置：默认值=None；最小值（含）=1；最大值（含）=1000。
    servings: int | None = Field(default=None, ge=1, le=1000)
    # 字段说明：confidence
    # 作用：当前抽取结果的置信度。
    # 类型：float。
    # 配置：最小值（含）=0；最大值（含）=1。
    confidence: float = Field(ge=0, le=1)
    # 字段说明：clarification_required
    # 作用：是否需要用户补充信息后才能可靠继续执行。
    # 类型：bool。
    # 初始值：False。
    clarification_required: bool = False
    # 字段说明：clarification_question
    # 作用：缺少关键信息或语义不确定时向用户提出的澄清问题。
    # 类型：str | None。
    # 初始值：None。
    clarification_question: str | None = None


# 方法说明：_normalize
# 作用：仅为候选召回归一化文本，不用该结果直接作业务决策。
# 入参：
#   value（str）：当前待转换或校验的值。
# 出参：str；文本字符串。
def _normalize(value: str) -> str:
    """仅为候选召回归一化文本，不用该结果直接作业务决策。"""
    return re.sub(r"[^0-9a-z\u3400-\u9fff]", "", value.casefold())


# 类说明（业务或基础设施实现类）：LocalModelRequestUnderstandingGateway
# 作用：调用 MLX 服务，并把通过校验的 JSON 转换成请求契约。
class LocalModelRequestUnderstandingGateway:
    """调用 MLX 服务，并把通过校验的 JSON 转换成请求契约。"""

    # 字段说明：backend_name
    # 作用：实际承担请求理解或服务实现的后端标识。
    # 初始值：'local_model'。
    backend_name = "local_model"

    # 方法说明：__init__
    # 作用：初始化本地模型请求理解适配器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   endpoint（str | None）：外部 API 的接口路径。
    #   catalog_path（str | Path）：规范菜名或本地菜谱目录路径；默认值为
    # 'training/nlu/recipe_catalog.json'。
    #   timeout（float）：操作超时上限，单位秒；默认值为 15.0。
    #   model_name（str）：当前调用使用的模型名称；默认值为 'default_model'。
    #   client（httpx.AsyncClient | None）：底层外部服务客户端；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        endpoint: str | None,
        *,
        catalog_path: str | Path = "training/nlu/recipe_catalog.json",
        timeout: float = 15.0,
        model_name: str = "default_model",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        # 实例属性说明：_endpoint
        # 作用：外部 API 的接口路径。
        self._endpoint = endpoint.rstrip("/") if endpoint else None
        # 实例属性说明：_catalog_path
        # 作用：规范菜名或本地菜谱目录路径。
        self._catalog_path = Path(catalog_path)
        # 实例属性说明：_timeout
        # 作用：操作超时上限，单位秒。
        self._timeout = timeout
        # 实例属性说明：_model_name
        # 作用：当前调用使用的模型名称。
        self._model_name = model_name
        # 实例属性说明：_client
        # 作用：底层外部服务客户端。
        self._client = client
        # 实例属性说明：_catalog
        # 作用：延迟加载的菜谱名称与别名目录，用于归一化请求目标。
        # 类型：list[dict[str, Any]] | None。
        # 初始值：None。
        self._catalog: list[dict[str, Any]] | None = None

    # 方法说明：_load_catalog
    # 作用：加载规范菜名，只用于限制模型可以选择的实体。
    # 入参：
    #   无显式入参。
    # 出参：list[dict[str, Any]]；文本字符串、由调用约定决定的数据对象组成的映射的集合。
    def _load_catalog(self) -> list[dict[str, Any]]:
        """加载规范菜名，只用于限制模型可以选择的实体。"""
        if self._catalog is None:
            with self._catalog_path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
            if isinstance(payload, dict):
                self._catalog = [
                    {"id": index, "name": str(name)}
                    for index, name in enumerate(payload, start=1)
                ]
            elif isinstance(payload, list):
                self._catalog = [
                    {"id": int(item["id"]), "name": str(item["name"])}
                    for item in payload
                    if isinstance(item, dict) and "id" in item and "name" in item
                ]
            else:
                raise ValueError("recipe candidate catalog must be an object or list")
        return self._catalog

    # 方法说明：_candidate_payload
    # 作用：召回可能的菜名和近期实体，但不在这里决定任务类型。
    # 入参：
    #   message（str）：本轮用户消息或问题文本。
    #   recent_context（ConversationHistory）：已加载的近期对话上下文。
    # 出参：tuple[list[dict[str, Any]], list[dict[str,
    # Any]]]；文本字符串、由调用约定决定的数据对象组成的映射的集合、文本字符串、由调用约定决定的数据对象组成的映射的集合组成的元组。
    def _candidate_payload(
        self, message: str, recent_context: ConversationHistory
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """召回可能的菜名和近期实体，但不在这里决定任务类型。"""
        catalog = self._load_catalog()
        normalized_message = _normalize(message)
        scored: list[tuple[float, dict[str, Any]]] = []
        rendered_names = list(recent_recipe_references(recent_context))
        catalog_by_name = {str(item["name"]): item for item in catalog}
        latest_assistant = next(
            (
                item.get("content", "")
                for item in reversed(recent_context)
                if item.get("role") == "assistant"
            ),
            "",
        )
        unquoted_names = sorted(
            (
                (latest_assistant.find(name), name)
                for name in catalog_by_name
                if name in latest_assistant and name not in rendered_names
            ),
            key=lambda item: item[0],
        )
        rendered_names.extend(name for _, name in unquoted_names)
        recent_entities: list[dict[str, Any]] = [
            catalog_by_name[name] for name in rendered_names if name in catalog_by_name
        ]
        recent_text = "\n".join(
            item.get("content", "")
            for item in recent_context
            if item.get("role") == "assistant"
        )
        for item in catalog:
            name = str(item["name"])
            normalized_name = _normalize(name)
            score = SequenceMatcher(None, normalized_message, normalized_name).ratio()
            if normalized_name and normalized_name in normalized_message:
                score += 1.0
            if name in recent_text:
                score += 0.75
            scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], len(str(pair[1]["name"]))))
        candidates = [item for score, item in scored[:10] if score >= 0.18]
        for item in recent_entities:
            if item not in candidates:
                candidates.append(item)
        return candidates[:10], recent_entities[:10]

    # 方法说明：_to_request_frame
    # 作用：把模型输出转换成稳定的应用层请求契约。
    # 入参：
    #   output（_ModelOutput）：当前模型或业务处理的输出。
    #   scenario（str | None）：当前模型调用场景；默认值为 None。
    #   menu_planning（MenuPlanningRequirements | None）：本轮复杂菜单规划要求；默认值为 None。
    # 出参：RequestFrame；归一化请求语义框架。
    @staticmethod
    def _to_request_frame(
        output: _ModelOutput,
        *,
        scenario: str | None = None,
        menu_planning: MenuPlanningRequirements | None = None,
    ) -> RequestFrame:
        """把模型输出转换成稳定的应用层请求契约。"""
        # “推荐某菜的做法”可能被模型标成推荐，但菜名和详情字段已明确；
        # 该跨字段冲突在契约边界修正，避免下游再次猜测。
        intent = "menu_planning" if menu_planning is not None else output.intent
        if (
            intent == "recipe_recommendation"
            and output.target.canonical_name
            and output.requested_fields
        ):
            intent = "recipe_detail"
        updates = [
            MemoryUpdate(kind=item.kind, value=item.value)
            for item in output.memory_updates
        ]
        for item in output.constraints:
            inferred_by_kind: dict[
                str, Literal["dislike", "allergy", "restriction"]
            ] = {
                "avoid_ingredient": "dislike",
                "allergy": "allergy",
                "restriction": "restriction",
            }
            inferred_kind = inferred_by_kind.get(item.kind)
            if inferred_kind and not any(
                update.kind == inferred_kind and update.value == item.value
                for update in updates
            ):
                updates.append(MemoryUpdate(kind=inferred_kind, value=item.value))
        current = tuple(
            CurrentConstraint(
                kind=cast(Literal["allergy", "restriction"], item.kind),
                value=item.value,
            )
            for item in output.constraints
            if item.kind in ("allergy", "restriction")
        )
        selection_categories = tuple(
            CurrentConstraint(kind="food_category", value=category)
            for item in output.constraints
            if item.kind == "include_ingredient"
            and item.required
            and (category := canonical_food_category(item.value)) is not None
        )
        avoided_categories = tuple(
            CurrentConstraint(kind="avoid_food_category", value=category)
            for item in output.constraints
            if item.kind == "avoid_ingredient"
            and item.required
            and (category := canonical_food_category(item.value)) is not None
        )
        current = (*current, *selection_categories, *avoided_categories)
        included = next(
            (
                item.value
                for item in output.constraints
                if item.kind == "include_ingredient"
            ),
            None,
        )
        turn_preferences = [
            DietaryPreference(
                kind=cast(
                    Literal[
                        "include_ingredient",
                        "avoid_ingredient",
                        "max_minutes",
                        "dietary_type",
                        "equipment",
                    ],
                    item.kind,
                ),
                value=item.value,
                required=item.required,
                source="input",
            )
            for item in output.constraints
            if item.kind
            in (
                "include_ingredient",
                "avoid_ingredient",
                "max_minutes",
                "dietary_type",
                "equipment",
            )
        ]
        for update_item in output.memory_updates:
            preference_kind: dict[
                str, Literal["include_ingredient", "avoid_ingredient"]
            ] = {
                "preference": "include_ingredient",
                "dislike": "avoid_ingredient",
            }
            kind = preference_kind.get(update_item.kind)
            if kind and not any(
                preference.kind == kind and preference.value == update_item.value
                for preference in turn_preferences
            ):
                turn_preferences.append(
                    DietaryPreference(
                        kind=kind,
                        value=update_item.value,
                        required=False,
                        source="input",
                    )
                )
        context_needs: list[
            Literal[
                "recent_conversation",
                "allergies",
                "dietary_restrictions",
                "food_preferences",
                "episodic_memory",
                "user_profile",
            ]
        ] = []
        if intent in {
            "recipe_recommendation",
            "menu_planning",
            "recipe_generation",
            "replace",
        }:
            context_needs.extend(
                ["allergies", "dietary_restrictions", "food_preferences"]
            )
        if intent in {"recipe_detail", "food_safety"}:
            context_needs.append("recent_conversation")
        if intent == "food_safety":
            context_needs.extend(["allergies", "dietary_restrictions"])
        return RawRequestFrame(
            tasks=(RequestTask(kind=intent),),
            memory_updates=tuple(updates),
            current_constraints=current,
            turn_preferences=tuple(turn_preferences),
            target=RequestTarget(
                recipe_name=output.target.canonical_name,
                ingredient=included,
            ),
            requested_fields=tuple(output.requested_fields),
            exact_match_required=bool(output.target.canonical_name),
            recommendation_count=(
                menu_planning.total_required
                if menu_planning is not None
                else output.recommendation_count
            ),
            servings=output.servings,
            scenario=scenario,
            menu_planning=menu_planning,
            context_needs=tuple(dict.fromkeys(context_needs)),
            confidence=output.confidence,
            clarification_question=output.clarification_question,
            backend="local_model:mlx",
            fallback_used=False,
        )

    # 方法说明：understand
    # 作用：从本轮文本与近期上下文形成校验后的请求语义框架。
    # 入参：
    #   message（str）：本轮用户消息或问题文本。
    #   recent_context（ConversationHistory）：已加载的近期对话上下文。
    # 出参：RequestFrame；归一化请求语义框架。
    async def understand(
        self, message: str, recent_context: ConversationHistory
    ) -> RequestFrame:
        if not self._endpoint:
            raise RuntimeError("request-understanding endpoint is not configured")
        # 始终提供有限的助手历史。“怎么做呢”没有显式菜名，历史是解析目标的必要证据。
        reference_context = recent_context[-6:]
        candidates, recent_entities = self._candidate_payload(
            message, reference_context
        )
        recent_assistant_turns = [
            item for item in reference_context if item.get("role") == "assistant"
        ][-3:]
        payload = {
            "message": message,
            "recent_turns": recent_assistant_turns,
            "recent_recipe_entities": recent_entities,
            "catalog_candidates": candidates,
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            request = {
                "model": self._model_name,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                "temperature": 0,
                "max_tokens": 420,
            }
            response = await client.post(
                f"{self._endpoint}/v1/chat/completions", json=request
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            output = _ModelOutput.model_validate_json(content)
            allowed_names = {str(item["name"]) for item in candidates}
            if (
                output.target.canonical_name is not None
                and output.target.canonical_name not in allowed_names
            ):
                raise ValueError("model selected a recipe outside catalog candidates")
            scenario, menu_planning = extract_menu_planning_requirements(message)
            servings_match = re.search(
                r"(?:给|供|为)?\s*([一二两三四五六七八九十]|\d{1,3})\s*个人",
                message,
            )
            if servings_match is None:
                servings_match = re.search(
                    r"(?:一家|全家)([一二两三四五六七八九十]|\d{1,3})口",
                    message,
                )
            servings = None
            if servings_match:
                values = {
                    "一": 1,
                    "二": 2,
                    "两": 2,
                    "三": 3,
                    "四": 4,
                    "五": 5,
                    "六": 6,
                    "七": 7,
                    "八": 8,
                    "九": 9,
                    "十": 10,
                }
                raw = servings_match.group(1)
                servings = int(raw) if raw.isdigit() else values[raw]
            frame = self._to_request_frame(
                output,
                scenario=scenario,
                menu_planning=menu_planning,
            )
            update: dict[str, object] = {"servings": servings or frame.servings}
            # 显式数量和本轮菜品分类属于不可丢失事实，小模型不能覆盖原文中的确定值。
            deterministic = RequestUnderstandingService().understand(
                message, reference_context
            )
            update["participants"] = deterministic.participants
            update["context_relation"] = deterministic.context_relation
            if deterministic.participants:
                update["memory_updates"] = deterministic.memory_updates
            if (
                deterministic.primary_task == "menu_planning"
                and deterministic.menu_planning is None
            ):
                # 无配额的配餐仍保留菜单语义，执行时再映射到普通推荐。
                update["tasks"] = deterministic.tasks
                update["meal_type"] = deterministic.meal_type
            if deterministic.primary_task == "clarify" and recent_recipe_references(
                reference_context
            ):
                # 基于实际展示顺序识别出的歧义，比模型依据无序候选猜测更可靠。
                update.update(
                    {
                        "tasks": deterministic.tasks,
                        "target": deterministic.target,
                        "requested_fields": (),
                        "exact_match_required": False,
                        "clarification_question": deterministic.clarification_question,
                    }
                )
            if deterministic.recommendation_count is not None:
                update["recommendation_count"] = deterministic.recommendation_count
            deterministic_categories = tuple(
                item
                for item in deterministic.current_constraints
                if item.kind in {"food_category", "avoid_food_category"}
            )
            if deterministic_categories:
                current_without_categories = tuple(
                    item
                    for item in frame.current_constraints
                    if item.kind not in {"food_category", "avoid_food_category"}
                )
                update["current_constraints"] = (
                    *current_without_categories,
                    *deterministic_categories,
                )
            temporary_scope = bool(
                re.search(r"今天|这顿|本轮|现在|这次", message)
            ) and not bool(re.search(r"以后|今后|一直|都不要|永远", message))
            if temporary_scope:
                update["memory_updates"] = tuple(
                    item
                    for item in frame.memory_updates
                    if item.kind not in {"preference", "dislike"}
                )
            has_explicit_recipe_count = bool(
                re.search(
                    r"([一二两三四五六七八九十]|\d{1,2})\s*(?:份|道|个(?!人))",
                    message,
                )
            )
            if servings and menu_planning is None and not has_explicit_recipe_count:
                # 用餐人数不能被模型误解释为推荐菜品数量。
                update["recommendation_count"] = None
            normalized = normalize_negation_scope(
                message, frame.model_copy(update=update)
            )
            canonical = RequestFrameSemanticValidator().normalize(
                normalized, deterministic=deterministic
            )
            # 当前模型契约尚未输出参与者归属，因此沿用确定性结构化结果。
            if deterministic.statements:
                canonical = canonical.model_copy(
                    update={"statements": deterministic.statements}
                )
            return canonical
        finally:
            if owns_client:
                await client.aclose()
