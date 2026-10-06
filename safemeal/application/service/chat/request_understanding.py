"""菜谱对话 Workflow 使用的确定性请求理解服务。"""

from __future__ import annotations

import re

from safemeal.application.contracts.workflow.request_frame import (
    CurrentConstraint,
    MemoryUpdate,
    RawRequestFrame,
    RequestFrame,
    RequestTarget,
    RequestTask,
)
from safemeal.application.service.memory.memory_extraction import UserMemoryExtractor
from safemeal.application.service.chat.menu_planning import (
    extract_menu_modification,
    extract_menu_planning_requirements,
    is_menu_planning_request,
)
from safemeal.application.service.recipes.food_category import (
    canonical_food_category,
)
from safemeal.application.service.chat.short_term_reference import (
    is_reference_only_target,
    resolve_recipe_reference,
)
from safemeal.application.service.chat.negation_scope import normalize_negation_scope
from safemeal.application.service.chat.request_frame_semantics import (
    RequestFrameSemanticValidator,
)


_DETAIL_TARGET_PATTERN = re.compile(
    r"^(.+?)(?:的)?(?:有什么|有哪些)?(?:材料|食材|配料|做法|步骤|怎么做|"
    r"(?:要|需要|得)?多久(?:能|可以)?(?:做好|做完)?|多长时间)(?:和(?:具体)?(?:做法|步骤))?(?:是什么|呢)?[?？]?$"
)
_DETAIL_PREFIX_PATTERN = re.compile(
    r"^(?:(?:请|麻烦|劳驾|能否|可以|能不能)?"
    r"(?:告诉我|介绍(?:一下)?|查询|查一下|说明(?:一下)?)|"
    r"请问|我想知道|我想了解)\s*"
)


class RequestUnderstandingService:
    backend_name = "rules"

    def understand(self, message: str, recent_context=()) -> RequestFrame:
        text = message.strip()
        number_values = {
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
        servings_match = re.search(
            r"(?:给|供|为)?\s*([一二两三四五六七八九十]|\d{1,3})\s*个人",
            text,
        )
        if servings_match is None:
            servings_match = re.search(
                r"(?:一家|全家)([一二两三四五六七八九十]|\d{1,3})口", text
            )
        servings = None
        if servings_match:
            raw_servings = servings_match.group(1)
            servings = (
                int(raw_servings)
                if raw_servings.isdigit()
                else number_values[raw_servings]
            )
        scenario, menu_planning = extract_menu_planning_requirements(text)
        modification_category, modification_count = extract_menu_modification(text)
        adaptive_menu = is_menu_planning_request(text) and menu_planning is None
        meal_type = (
            "breakfast"
            if "早餐" in text or "早饭" in text
            else "lunch"
            if "午餐" in text or "午饭" in text
            else "dinner"
            if "晚餐" in text or "晚饭" in text
            else None
        )
        extraction = UserMemoryExtractor().extract(text)
        temporary_scope = bool(
            re.search(r"今天|这顿|本轮|现在|这次", text)
        ) and not bool(re.search(r"以后|今后|一直|都不要|永远", text))
        updates: list[MemoryUpdate] = []
        constraints: list[CurrentConstraint] = []
        for candidate in extraction.candidates:
            kind = {
                "taste_preference": "preference",
                "taste_dislike": "dislike",
                "dietary_allergy": "allergy",
                "dietary_restriction": "restriction",
            }.get(candidate.memory_type)
            if kind is None:
                continue
            if temporary_scope and kind in {"preference", "dislike"}:
                continue
            # 家庭成员的本餐要求只属于当前用餐，不能据此修改账号所有者画像。
            persist = not (
                kind == "restriction"
                and is_menu_planning_request(text)
                and re.search(r"媳妇|老婆|妻子|儿子|女儿|孩子", text)
            )
            if persist:
                updates.append(MemoryUpdate(kind=kind, value=candidate.key))
            if kind in {"allergy", "restriction"}:
                constraints.append(CurrentConstraint(kind=kind, value=candidate.key))

        fields: list[str] = []
        if any(term in text for term in ("材料", "食材", "配料")):
            fields.append("ingredients")
        if any(term in text for term in ("做法", "步骤", "怎么做")):
            fields.append("steps")
        if any(term in text for term in ("多久", "多长时间", "耗时")):
            fields.append("time")

        target_name: str | None = None
        detail = _DETAIL_TARGET_PATTERN.search(text)
        if detail:
            target_name = re.split(r"[，,。；;]", detail.group(1))[-1].strip()
            # 礼貌用语不属于规范菜名，匹配后统一移除，避免精确查询失败。
            target_name = _DETAIL_PREFIX_PATTERN.sub("", target_name).strip()
            target_name = re.sub(
                r"^(?:我(?:很)?爱吃|我喜欢|我想吃)", "", target_name
            ).strip()
            target_name = target_name.rstrip("的").strip()
        clarification_question: str | None = None
        if fields and (target_name is None or is_reference_only_target(target_name)):
            resolved, clarification_question = resolve_recipe_reference(
                text, list(recent_context)[-6:]
            )
            if resolved:
                target_name = resolved

        # 本轮明确点选的品类进入强筛选条件；长期喜好仍保留为偏好，不在此升级。
        category_match = re.search(
            r"(?:推荐|来|给我|想吃|想要吃|今天(?:就)?想吃)"
            r"(?:[一二两三四五六七八九十\d]+(?:份|道|个)?)?"
            r"(鱼类|海鲜|素菜|素食|鱼)(?:菜|食谱)?",
            text,
        )
        if category_match:
            category = canonical_food_category(category_match.group(1))
            if category is not None:
                constraints.append(
                    CurrentConstraint(kind="food_category", value=category)
                )
        avoided_category = re.search(
            r"(?:今天|这顿|本轮|现在|这次).{0,6}(?:不想吃|不吃|不要)"
            r"(鱼类|海鲜|素菜|素食|鱼)",
            text,
        )
        if avoided_category:
            category = canonical_food_category(avoided_category.group(1))
            if category is not None:
                constraints.append(
                    CurrentConstraint(kind="avoid_food_category", value=category)
                )

        positive_categories = {
            item.value for item in constraints if item.kind == "food_category"
        }
        if positive_categories:
            constraints = [
                item
                for item in constraints
                if not (
                    item.kind == "restriction"
                    and canonical_food_category(item.value) in positive_categories
                )
            ]
            updates = [
                item
                for item in updates
                if not (
                    item.kind == "restriction"
                    and canonical_food_category(item.value) in positive_categories
                )
            ]

        tasks: list[RequestTask] = []
        if modification_category is not None:
            tasks.append(RequestTask(kind="replace"))
        elif clarification_question:
            tasks.append(RequestTask(kind="clarify"))
        elif menu_planning is not None or adaptive_menu:
            tasks.append(RequestTask(kind="menu_planning"))
        elif re.search(r"\d+\s*g.*(?:蛋白质|热量|脂肪|碳水)", text, re.I):
            tasks.append(RequestTask(kind="nutrition_query"))
            fields.append("nutrition")
        elif re.search(r"(?:这个|那个|它).*(?:能吃|可以吃|安全吗)", text):
            tasks.append(RequestTask(kind="food_safety"))
        elif target_name and fields:
            tasks.append(RequestTask(kind="recipe_detail"))
        elif any(term in text for term in ("生成", "设计", "创作", "原创")):
            tasks.append(RequestTask(kind="recipe_generation"))
        elif any(
            term in text
            for term in (
                "推荐",
                "吃什么",
                "吃点",
                "想吃",
                "有没有什么",
                "几道",
                "家常菜",
            )
        ):
            tasks.append(RequestTask(kind="recipe_recommendation"))
        elif any(term in text for term in ("食材", "菜", "食谱", "烹饪", "营养")):
            tasks.append(RequestTask(kind="knowledge"))

        clear = bool(tasks)
        recommendation_count: int | None = None
        if menu_planning is not None:
            recommendation_count = menu_planning.total_required
        elif tasks and tasks[0].kind in {"recipe_recommendation", "recipe_generation"}:
            count_match = re.search(
                r"(?:推荐|来|给我|想要)?\s*([一二两三四五六七八九十]|\d{1,2})\s*(?:份|道|个(?!人))",
                text,
            )
            if count_match:
                chinese_counts = {
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
                raw_count = count_match.group(1)
                recommendation_count = min(
                    10,
                    chinese_counts.get(
                        raw_count, int(raw_count) if raw_count.isdigit() else 3
                    ),
                )
            elif re.search(r"几(?:份|道|个)", text):
                recommendation_count = 3
        context_needs: list[str] = []
        primary = tasks[0].kind if tasks else "out_of_scope"
        if primary in {
            "recipe_recommendation",
            "menu_planning",
            "recipe_generation",
            "replace",
        }:
            context_needs.extend(
                ["allergies", "dietary_restrictions", "food_preferences"]
            )
        elif primary == "food_safety":
            context_needs.extend(
                ["recent_conversation", "allergies", "dietary_restrictions"]
            )
        elif primary == "recipe_detail":
            context_needs.append("recent_conversation")
        participants = tuple(
            dict.fromkeys(
                owner
                for token, owner in (
                    ("媳妇", "spouse"),
                    ("老婆", "spouse"),
                    ("妻子", "spouse"),
                    ("儿子", "child"),
                    ("女儿", "child"),
                    ("我自己", "self"),
                )
                if token in text
            )
        )
        context_relation = (
            "reference"
            if fields and (target_name is None or is_reference_only_target(target_name))
            else "modification"
            if modification_category is not None
            or re.search(r"还是|重新|重选|重来|替换|改成|换成|现在想|不要了", text)
            else "continuation"
            if re.search(r"再来|按刚才|继续|同样", text)
            else "new_task"
        )
        frame = RawRequestFrame(
            tasks=tuple(tasks),
            memory_updates=tuple(updates),
            current_constraints=tuple(constraints),
            participants=participants,
            context_relation=context_relation,
            operation="replace" if modification_category is not None else None,
            target=RequestTarget(
                recipe_name=target_name,
                menu_category=modification_category,
            ),
            requested_fields=tuple(fields),
            exact_match_required=bool(target_name),
            recommendation_count=modification_count or recommendation_count,
            servings=servings,
            meal_type=meal_type,
            scenario=scenario,
            menu_planning=menu_planning,
            context_needs=tuple(dict.fromkeys(context_needs)),
            confidence=0.9 if clear and primary != "food_safety" else 0.55,
            understanding_status=(
                "accepted" if clear and primary != "food_safety" else "low_confidence"
            ),
            backend=self.backend_name,
            fallback_used=not clear or primary == "food_safety",
            clarification_question=clarification_question,
        )
        normalized = normalize_negation_scope(text, frame)
        canonical = RequestFrameSemanticValidator().normalize(normalized)
        owned = []
        for statement in canonical.statements:
            mention = "辣" if statement.value == "non_spicy" else statement.value
            position = text.find(mention)
            prefix = text[max(0, position - 8) : position] if position >= 0 else ""
            owner = (
                "spouse"
                if re.search(r"媳妇|老婆|妻子", prefix)
                else "child"
                if re.search(r"儿子|女儿|孩子", prefix)
                else "self"
            )
            owned.append(statement.model_copy(update={"owner": owner}))
        return canonical.model_copy(update={"statements": tuple(owned)})


class RuleBasedRequestUnderstandingGateway:
    """无外部依赖的规则实现，也作为本地模型不可用时的降级路径。"""

    backend_name = "rules"

    def __init__(self, service: RequestUnderstandingService | None = None) -> None:
        self._service = service or RequestUnderstandingService()

    async def understand(self, message: str, recent_context=()) -> RequestFrame:
        return self._service.understand(message, recent_context)
