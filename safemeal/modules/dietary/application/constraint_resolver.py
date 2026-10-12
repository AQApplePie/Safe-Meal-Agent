"""把多来源要求归并为本轮权威约束。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from safemeal.modules.dietary.contracts.control_plane import (
    ResolvedConstraints,
)
from safemeal.shared.contracts.request_frame import RequestFrame
from safemeal.shared.contracts.semantic import ConstraintStatement
from safemeal.shared.types import JsonObject


# 类说明（业务或基础设施实现类）：ConstraintResolver
# 作用：实现饮食约束解析器，封装该组件的业务处理与依赖协作。
class ConstraintResolver:
    # 方法说明：resolve
    # 作用：在饮食约束解析器中合并并解析当前输入的业务要求。
    # 入参：
    #   frame（RequestFrame）：归一化请求语义框架。
    #   memories（Iterable[JsonObject]）：已经加载的用户长期记忆。
    #   previous（ResolvedConstraints | None）：此前状态或已有活动记录；默认值为 None。
    # 出参：ResolvedConstraints；合并后的饮食约束。
    def resolve(
        self,
        frame: RequestFrame,
        memories: Iterable[JsonObject],
        *,
        previous: ResolvedConstraints | None = None,
    ) -> ResolvedConstraints:
        statements: list[ConstraintStatement] = []
        kind: Literal["allergy", "restriction", "avoid", "include"]
        strength: Literal["hard_safety", "soft_preference", "menu_goal"]
        for memory in memories:
            memory_type = str(memory.get("memory_type") or "")
            value = str(memory.get("memory_key") or "").strip()
            if not value:
                continue
            if memory_type == "dietary_allergy":
                kind, strength = "allergy", "hard_safety"
            elif memory_type == "dietary_restriction":
                kind, strength = "restriction", "hard_safety"
            elif memory_type == "taste_dislike":
                kind, strength = "avoid", "soft_preference"
            elif memory_type == "taste_preference":
                kind, strength = "include", "menu_goal"
            else:
                continue
            statements.append(
                ConstraintStatement(
                    type=kind,
                    value=value,
                    strength=strength,
                    source="persistent_memory",
                    scope="persistent",
                )
            )

        if frame.context_relation in {"continuation", "modification"} and previous:
            statements.extend(
                item.model_copy(update={"source": "explicit_carryover"})
                for item in previous.active
                if item.scope in {"current_turn", "current_meal", "conversation"}
            )
        statements.extend(frame.statements)

        selected: dict[tuple[str, str], ConstraintStatement] = {}
        for item in statements:
            dimension = (
                ("taste", item.owner)
                if item.type == "taste"
                else (item.type, item.owner)
            )
            selected[dimension] = item
        active = tuple(selected.values())
        return ResolvedConstraints(
            hard_safety=tuple(i for i in active if i.strength == "hard_safety"),
            strong_requirements=tuple(
                i for i in active if i.strength == "strong_requirement"
            ),
            soft_preferences=tuple(
                i for i in active if i.strength == "soft_preference"
            ),
            menu_goals=tuple(i for i in active if i.strength == "menu_goal"),
        )


__all__ = ["ConstraintResolver"]
