"""与具体模型无关的单轮请求理解契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from safemeal.application.contracts.dietary_safety.requirements import (
    DietaryPreference,
)
from safemeal.application.contracts.workflow.semantic import (
    ConstraintScope as ConstraintScope,
    ConstraintSource as ConstraintSource,
    ConstraintStatement,
    ConstraintStrength as ConstraintStrength,
    ContextRelation,
)


class RequestTask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal[
        "recipe_detail",
        "recipe_recommendation",
        "menu_planning",
        "recipe_generation",
        "knowledge",
        "nutrition_query",
        "food_safety",
        "replace",
        "memory",
        "clarify",
        "out_of_scope",
    ]


MenuCategory = Literal[
    "cold_dish",
    "hot_dish",
    "vegetarian",
    "meat",
    "soup",
    "staple",
]


class CategoryQuota(BaseModel):
    """复杂菜单中一个可确定计数的分类配额。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    category: MenuCategory
    count: int = Field(ge=1, le=20)


class MenuPlanningRequirements(BaseModel):
    """必须由代码验证完成度的菜单规划要求。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    category_quotas: tuple[CategoryQuota, ...] = Field(min_length=1, max_length=12)
    distinct_recipes: bool = True
    allow_cross_category_counting: bool = False

    @property
    def total_required(self) -> int:
        return sum(item.count for item in self.category_quotas)


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["preference", "dislike", "allergy", "restriction"]
    value: str = Field(min_length=1, max_length=100)


class CurrentConstraint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["allergy", "restriction", "food_category", "avoid_food_category"]
    value: str = Field(min_length=1, max_length=100)


class RequestTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    recipe_name: str | None = Field(default=None, max_length=255)
    ingredient: str | None = Field(default=None, max_length=100)
    menu_category: MenuCategory | None = None


class RequestFrame(BaseModel):
    """当前用户输入经过归一化后形成的唯一业务语义事实。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    tasks: tuple[RequestTask, ...] = ()
    memory_updates: tuple[MemoryUpdate, ...] = ()
    current_constraints: tuple[CurrentConstraint, ...] = ()
    turn_preferences: tuple[DietaryPreference, ...] = ()
    statements: tuple[ConstraintStatement, ...] = ()
    participants: tuple[str, ...] = ()
    context_relation: ContextRelation = "new_task"
    operation: Literal["replace"] | None = None
    canonical: bool = True
    target: RequestTarget = Field(default_factory=RequestTarget)
    requested_fields: tuple[
        Literal["ingredients", "steps", "time", "nutrition"], ...
    ] = ()
    exact_match_required: bool = False
    recommendation_count: int | None = Field(default=None, ge=1, le=100)
    servings: int | None = Field(default=None, ge=1, le=1000)
    # 即使用户没有提供分类配额，用餐时段仍用于普通配餐推荐。
    meal_type: Literal["breakfast", "lunch", "dinner"] | None = None
    scenario: str | None = Field(default=None, max_length=100)
    menu_planning: MenuPlanningRequirements | None = None
    context_needs: tuple[
        Literal[
            "recent_conversation",
            "allergies",
            "dietary_restrictions",
            "food_preferences",
            "episodic_memory",
            "user_profile",
        ],
        ...,
    ] = ()
    confidence: float = Field(default=1.0, ge=0, le=1)
    understanding_status: Literal[
        "accepted", "low_confidence", "fallback", "incomplete"
    ] = "accepted"
    backend: str = "rules"
    fallback_used: bool = False
    clarification_question: str | None = Field(default=None, max_length=300)
    validation_errors: tuple[str, ...] = Field(default_factory=tuple, max_length=10)

    @property
    def primary_task(self) -> str:
        return self.tasks[0].kind if self.tasks else "out_of_scope"


# 原始契约尚未通过语义归一化，不能直接驱动 Planner。
class RawRequestFrame(RequestFrame):
    canonical: bool = False


CanonicalRequestFrame = RequestFrame
