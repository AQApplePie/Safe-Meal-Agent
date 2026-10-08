"""定义跨层传递的稳定数据契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ConstraintSource = Literal[
    "current_input",
    "explicit_carryover",
    "persistent_memory",
    "history_context",
]
ConstraintScope = Literal["current_turn", "current_meal", "conversation", "persistent"]
ConstraintStrength = Literal[
    "hard_safety", "strong_requirement", "soft_preference", "menu_goal"
]
ContextRelation = Literal["new_task", "continuation", "reference", "modification"]


class ConstraintStatement(BaseModel):

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal[
        "allergy",
        "restriction",
        "avoid",
        "include",
        "food_category",
        "avoid_food_category",
        "max_minutes",
        "dietary_type",
        "equipment",
        "taste",
    ]
    value: str = Field(min_length=1, max_length=200)
    owner: str = Field(default="self", min_length=1, max_length=80)
    strength: ConstraintStrength
    source: ConstraintSource = "current_input"
    scope: ConstraintScope = "current_turn"
