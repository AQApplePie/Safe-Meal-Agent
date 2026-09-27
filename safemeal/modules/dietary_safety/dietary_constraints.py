"""Dietary-safety application DTOs, extraction, and evidence mapping.

这个模块不直接访问数据库，也不调用 LLM，也不依赖 Agent 状态模型。它只负责
抽取饮食约束、匹配禁忌食材，并根据结构化候选证据给出安全分类。
"""

from __future__ import annotations

import re
from typing import Sequence, Iterable, List, Literal, Optional, Protocol

from pydantic import BaseModel, Field

from safemeal.modules.dietary_safety.ingredient_terms import (
    DIETARY_TRIGGER_TERMS,
    INGREDIENT_ALIASES,
    INGREDIENT_KEYS,
    NEGATED_DIETARY_PATTERNS,
    RECIPE_NAME_KEYS,
)
from safemeal.application.contracts.conversation.models import ConversationMessage
from safemeal.shared.types import JsonObject

from .recipe_safety import (
    Evidence,
    EvidenceBundle,
    Ingredient,
    RecipeSafetyEvaluator,
    RecipeSafetyInput,
    SafetyStatus,
)


class DietaryEvidenceObservation(Protocol):
    """Minimal evidence shape consumed by dietary safety filtering."""

    call_id: str
    tool_name: str
    ok: bool
    data: object


class DietaryConstraint(BaseModel):
    """从用户问题中提取出的饮食安全约束。"""

    active: bool = Field(description="是否识别到忌口/过敏等饮食约束。")
    trigger_terms: List[str] = Field(default_factory=list, description="命中的触发词。")
    raw_ingredients: List[str] = Field(
        default_factory=list, description="用户原始提到的食材。"
    )
    excluded_ingredients: List[str] = Field(
        default_factory=list,
        description="展开后的禁忌食材或同义表达。",
    )
    strictness: str = Field(
        default="hard_exclusion",
        description="过滤严格度；过敏/忌口默认硬排除。",
    )


class RecipeSafetyRecord(BaseModel):
    """一道候选菜在忌口过滤后的分类结果。"""

    name: str = Field(description="菜名或候选项名称。")
    ingredients: List[str] = Field(
        default_factory=list, description="已确认的结构化食材。"
    )
    matched_forbidden_ingredients: List[str] = Field(
        default_factory=list,
        description="命中的禁忌食材表达。",
    )
    safety_status: Literal["safe", "excluded", "unknown"] = Field(
        default="unknown",
        description="安全分类：safe 可推荐，excluded 必须排除，unknown 证据不足。",
    )
    evidence_call_ids: List[str] = Field(
        default_factory=list,
        description="支持该判断的原始 Tool call_id。",
    )
    evidence: List[JsonObject] = Field(
        default_factory=list,
        description="来自工具或数据库的结构化证据片段。",
    )
    reason: str = Field(description="分类理由。")


class DietarySafetyResult(BaseModel):
    """一次确定性忌口过滤的完整输出。"""

    active: bool
    constraint: DietaryConstraint
    safe_recipes: List[RecipeSafetyRecord] = Field(default_factory=list)
    excluded_recipes: List[RecipeSafetyRecord] = Field(default_factory=list)
    unknown_recipes: List[RecipeSafetyRecord] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)


def _unique(items: Iterable[str]) -> List[str]:
    """保持输入顺序去重，同时过滤空字符串。"""

    seen = set()
    result = []
    for item in items:
        value = str(item).strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def extract_dietary_constraint(question: str) -> DietaryConstraint:
    """从用户问题中抽取忌口/过敏约束。

    这里故意采用保守规则，而不是再调用一次 LLM。规则抽取不会覆盖所有自然语言
    表达，但它稳定、可测试，并且足以触发后续确定性安全过滤。
    """

    # Remove only the negated clause instead of disabling the entire message. A mixed
    # statement such as "花生不是过敏原，但我对鸡蛋过敏" must retain the positive
    # chicken-egg constraint.
    working_question = question
    negated_clause_found = False
    explicitly_negated_ingredients = {
        name
        for name in INGREDIENT_ALIASES
        if any(
            re.search(pattern, question)
            for pattern in (
                rf"(?:不是|并非|没有|不再)(?:对)?{re.escape(name)}[^，。；;,.]{{0,6}}(?:过敏|忌口)",
                rf"对{re.escape(name)}[^，。；;,.]{{0,4}}不过敏",
                rf"{re.escape(name)}[^，。；;,.]{{0,4}}(?:不是|并非|不再是)[^，。；;,.]{{0,6}}(?:过敏原|忌口)",
            )
        )
    }
    for pattern in NEGATED_DIETARY_PATTERNS:
        working_question, substitutions = re.subn(pattern, " ", working_question)
        negated_clause_found = negated_clause_found or substitutions > 0

    trigger_terms = [term for term in DIETARY_TRIGGER_TERMS if term in working_question]
    raw_ingredients: List[str] = []
    for name in sorted(INGREDIENT_ALIASES, key=len, reverse=True):
        if name not in working_question or name in explicitly_negated_ingredients:
            continue
        if any(name in existing for existing in raw_ingredients):
            continue
        raw_ingredients.append(name)

    # 尝试抓取“不能吃 X / 对 X 过敏 / 忌口 X / 避开 X”等短语中的显式食材。
    phrase_patterns = (
        re.compile(r"(?:不能吃|不吃|不要吃|忌口|避开|不含)([^，。；;,.]{1,24})"),
        re.compile(r"对([^，。；;,.]{1,24}?)过敏"),
    )
    for phrase_pattern in phrase_patterns:
        for match in phrase_pattern.finditer(working_question):
            phrase = match.group(1)
            phrase = re.sub(
                r"(?:的)?(?:菜|食物|料理|成分|东西).*$",
                "",
                phrase,
            )
            for part in re.split(r"[、,，/和及与\s]+", phrase):
                part = part.strip("：:的类等尤其要并且请从里推荐判断是否适合")
                if 1 <= len(part) <= 8 and part not in explicitly_negated_ingredients:
                    raw_ingredients.append(part)

    expanded: List[str] = []
    for item in raw_ingredients:
        expanded.extend(INGREDIENT_ALIASES.get(item, [item]))

    active = bool(trigger_terms and expanded)
    return DietaryConstraint(
        active=active,
        trigger_terms=_unique(trigger_terms),
        raw_ingredients=_unique(raw_ingredients),
        excluded_ingredients=_unique(expanded),
        strictness=(
            "hard_exclusion"
            if active
            else (
                "not_applicable_negated_constraint"
                if negated_clause_found
                else "hard_exclusion"
            )
        ),
    )


def merge_dietary_constraints(
    constraints: Iterable[DietaryConstraint],
    *,
    strictness: str = "hard_exclusion_contextual",
) -> DietaryConstraint:
    """合并多轮对话中识别到的忌口/过敏约束。

    Args:
        constraints: 需要合并的约束集合，通常来自历史 user 消息和当前 user 消息。
        strictness: 合并后写入 Trace 的严格度标记，用于区分“单轮抽取”和“上下文继承”。

    Returns:
        合并后的饮食约束。只有至少一个输入约束 active=True 时，结果才会 active=True。

    设计说明：
    - 只做并集，不做自动删除，避免用户前文说“花生过敏”、后文没重复时被误清空；
    - 顺序去重，保证Trace和输出稳定；
    - 真正的“取消/否定约束”由当前轮显式否定逻辑处理，不在这里猜测。
    """

    active_constraints = [constraint for constraint in constraints if constraint.active]
    if not active_constraints:
        return DietaryConstraint(
            active=False,
            trigger_terms=[],
            raw_ingredients=[],
            excluded_ingredients=[],
            strictness=strictness,
        )

    return DietaryConstraint(
        active=True,
        trigger_terms=_unique(
            term
            for constraint in active_constraints
            for term in constraint.trigger_terms
        ),
        raw_ingredients=_unique(
            ingredient
            for constraint in active_constraints
            for ingredient in constraint.raw_ingredients
        ),
        excluded_ingredients=_unique(
            ingredient
            for constraint in active_constraints
            for ingredient in constraint.excluded_ingredients
        ),
        strictness=strictness,
    )


def extract_dietary_constraint_from_history(
    conversation_history: Iterable[ConversationMessage],
) -> DietaryConstraint:
    """从历史对话中继承仍然有效的忌口/过敏约束。

    Args:
        conversation_history: Agent 初始化节点整理出的历史消息，元素通常包含 role/content。

    Returns:
        从历史 user 消息中合并得到的饮食约束。

    注意：
    - 只扫描 role=user/human 的消息，避免把 assistant 回答中的菜名或解释误当成用户约束；
    - 不扫描系统消息，避免 Prompt 或工具说明污染业务约束；
    - 当前函数只负责“继承”，是否被当前轮否定由
      extract_contextual_dietary_constraint 统一处理。
    """

    constraints: List[DietaryConstraint] = []
    for message in conversation_history:
        role = str(message.get("role", "")).lower()
        if role not in {"user", "human"}:
            continue
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        constraint = extract_dietary_constraint(content)
        if constraint.active:
            constraints.append(constraint)

    return merge_dietary_constraints(
        constraints,
        strictness="hard_exclusion_inherited_context",
    )


def extract_contextual_dietary_constraint(
    question: str,
    conversation_history: Iterable[ConversationMessage],
) -> DietaryConstraint:
    """结合当前问题和历史对话，得到本轮 Agent 应执行的忌口/过敏约束。

    Args:
        question: 当前轮用户问题。
        conversation_history: 当前轮之前的对话历史。

    Returns:
        本轮有效的饮食约束。

    规则：
    1. 当前轮显式否定忌口/过敏时，不继承历史约束；
    2. 当前轮有新约束时，与历史约束合并；
    3. 当前轮没有约束时，继承历史 user 消息中的有效约束。
    """

    current_constraint = extract_dietary_constraint(question)
    if current_constraint.strictness == "not_applicable_negated_constraint":
        return current_constraint

    history_constraint = extract_dietary_constraint_from_history(conversation_history)
    return merge_dietary_constraints(
        [history_constraint, current_constraint],
        strictness=(
            "hard_exclusion_contextual"
            if history_constraint.active
            else current_constraint.strictness
        ),
    )


def dietary_constraint_from_user_memories(
    user_memories: Iterable[JsonObject],
) -> DietaryConstraint:
    """把长期用户记忆中的饮食硬约束转换为本轮可执行的安全过滤约束。

    Args:
        user_memories: 从用户长期记忆表读取的活跃记忆。

    Returns:
        由 dietary_allergy/dietary_restriction 记忆合并出的饮食约束。

    长期记忆中的“过敏/忌口”属于高风险硬约束，不能只作为软偏好交给 LLM。
    这里把它转为 DietaryConstraint，复用已有 deterministic safety filter。
    """

    constraints: List[DietaryConstraint] = []
    for memory in user_memories:
        memory_type = str(memory.get("memory_type", ""))
        if memory_type not in {"dietary_allergy", "dietary_restriction"}:
            continue
        key = str(memory.get("memory_key", "")).strip()
        if not key:
            continue

        metadata = memory.get("memory_metadata") or {}
        excluded = (
            metadata.get("excluded_ingredients") if isinstance(metadata, dict) else None
        )
        if not excluded:
            excluded = INGREDIENT_ALIASES.get(key, [key])

        constraints.append(
            DietaryConstraint(
                active=True,
                trigger_terms=["长期记忆"],
                raw_ingredients=[key],
                excluded_ingredients=_unique(str(item) for item in excluded),
                strictness="hard_exclusion_long_term_memory",
            )
        )

    return merge_dietary_constraints(
        constraints,
        strictness="hard_exclusion_long_term_memory",
    )


def _nested_values(value: object) -> Iterable[object]:
    """递归遍历字典/列表中的全部值。"""

    if isinstance(value, dict):
        for item in value.values():
            yield from _nested_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _nested_values(item)
    else:
        yield value


def _find_recipe_name(payload: object) -> Optional[str]:
    """从工具返回的一行记录里尽量找出菜名。"""

    if isinstance(payload, dict):
        for key in RECIPE_NAME_KEYS:
            if key in payload and payload[key]:
                return str(payload[key])
        for value in payload.values():
            nested = _find_recipe_name(value)
            if nested:
                return nested
    return None


def _ingredient_values(payload: object) -> List[str]:
    """从记录中只抽取结构化食材字段，避免用菜名/描述做误伤匹配。"""

    values: List[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key).casefold()
            if any(marker.casefold() in key_text for marker in INGREDIENT_KEYS):
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, (list, tuple)) and item:
                            values.append(str(item[0]))
                        elif isinstance(item, dict):
                            nested_ingredient = item.get("ingredient")
                            nested_name = (
                                (
                                    nested_ingredient.get("name")
                                    if isinstance(nested_ingredient, dict)
                                    else nested_ingredient
                                )
                                or item.get("name")
                                or item.get("ingredient_name")
                                or item.get("食材")
                            )
                            if nested_name:
                                values.append(str(nested_name))
                            else:
                                values.extend(str(v) for v in _nested_values(item))
                        else:
                            values.append(str(item))
                elif value:
                    values.append(str(value))
            else:
                values.extend(_ingredient_values(value))
    elif isinstance(payload, list):
        for item in payload:
            values.extend(_ingredient_values(item))
    return _unique(values)


def _has_ingredient_evidence(payload: object) -> bool:
    """判断一条记录是否包含食材字段或食材关系证据。"""

    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key).casefold()
            if any(marker.casefold() in key_text for marker in INGREDIENT_KEYS):
                return bool(value)
            if _has_ingredient_evidence(value):
                return True
    elif isinstance(payload, list):
        return any(_has_ingredient_evidence(item) for item in payload)
    return False


def _candidate_rows(data: object) -> List[object]:
    """从不同 Tool 的返回结构中抽取候选记录。"""

    if not isinstance(data, dict):
        return []
    rows: List[object] = []
    for key in ("safe_recipes", "excluded_recipes", "unknown_recipes"):
        if isinstance(data.get(key), list):
            rows.extend(data[key])
    if rows:
        return rows
    if isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(data.get("rows"), list):
        return data["rows"]
    if isinstance(data.get("documents"), list):
        return data["documents"]
    if _find_recipe_name(data) and "ingredients" in data:
        return [data]
    if data.get("response"):
        return [{"response": data.get("response")}]
    return []


def build_dietary_safety_result(
    *,
    constraint: DietaryConstraint,
    observations: Sequence[DietaryEvidenceObservation],
) -> DietarySafetyResult:
    """基于已有候选证据进行忌口安全过滤。

    Args:
        constraint: 从用户问题中抽取的饮食约束。
        observations: 当前已经获得的工具观察结果。
    """

    result = DietarySafetyResult(active=constraint.active, constraint=constraint)
    if not constraint.active:
        return result

    inspected_records = 0
    ingredient_evidence_records = 0
    safety_evaluator = RecipeSafetyEvaluator()
    grouped: dict[str, list[tuple[DietaryEvidenceObservation, object]]] = {}
    trusted_tools = {
        "search_recipes",
        "get_recipe",
        "recommend_recipes",
        "generate_recipe",
        "dietary_safe_recipe_query",
    }
    for observation in observations:
        if not observation.ok or observation.tool_name not in trusted_tools:
            continue
        for row in _candidate_rows(observation.data):
            inspected_records += 1
            name = _find_recipe_name(row)
            if name:
                grouped.setdefault(name, []).append((observation, row))

    for name, records in grouped.items():
        ingredients: list[str] = []
        evidence = []
        complete = True
        conflict = False
        generated_violations: list[str] = []
        for observation, row in records:
            values = _ingredient_values(row)
            ingredients.extend(values)
            has_evidence = bool(values) and _has_ingredient_evidence(row)
            if isinstance(row, dict):
                has_evidence = (
                    has_evidence and row.get("ingredients_complete", True) is not False
                )
                has_evidence = has_evidence and row.get("safety_status") != "unknown"
                conflict = conflict or bool(row.get("conflicting_sources"))
                if row.get("safety_status") == "excluded":
                    generated_violations.extend(
                        row.get("matched_forbidden_ingredients")
                        or constraint.excluded_ingredients
                    )
            complete = complete and has_evidence
            ingredient_evidence_records += int(has_evidence)
            evidence.append(Evidence(observation.tool_name, observation.call_id))
            if observation.tool_name == "generate_recipe":
                from safemeal.modules.recipe_catalog.generated_recipe import (
                    GeneratedRecipe,
                )
                from .generated_safety import generated_recipe_violations

                try:
                    generated = GeneratedRecipe.model_validate(row)
                    generated_violations.extend(
                        generated_recipe_violations(
                            generated, constraint.excluded_ingredients
                        )
                    )
                except (ValueError, TypeError):
                    complete = False
        ingredients = _unique(ingredients)
        # All same-name evidence is considered: a later conflicting source cannot be
        # hidden by the first source or by the model's candidate ordering.
        decision = safety_evaluator.evaluate(
            RecipeSafetyInput(
                recipe_name=name,
                ingredients=tuple(
                    Ingredient(item) for item in [*ingredients, *generated_violations]
                ),
                forbidden_terms=tuple(constraint.excluded_ingredients),
                evidence=EvidenceBundle(
                    items=tuple(evidence),
                    ingredients_complete=complete,
                    conflicting_sources=("candidate_sources",) if conflict else (),
                ),
            )
        )
        record = RecipeSafetyRecord(
            name=name,
            ingredients=ingredients,
            matched_forbidden_ingredients=list(decision.matched_ingredients),
            safety_status=decision.status.value,
            evidence_call_ids=_unique(item.reference for item in evidence),
            reason=decision.reason,
        )
        if decision.status is SafetyStatus.UNSAFE:
            result.excluded_recipes.append(record)
        elif decision.status is SafetyStatus.SAFE:
            result.safe_recipes.append(record)
        else:
            result.unknown_recipes.append(record)

    if inspected_records == 0:
        result.missing_information.append(
            "尚未获得候选菜及其食材证据，不能进行忌口安全过滤。"
        )
    if inspected_records > 0 and ingredient_evidence_records == 0:
        result.missing_information.append(
            "已有候选记录，但缺少主食材/辅料等结构化食材字段。"
        )
    if not result.safe_recipes:
        result.missing_information.append("暂未确认任何可安全推荐的菜品。")
    return result
