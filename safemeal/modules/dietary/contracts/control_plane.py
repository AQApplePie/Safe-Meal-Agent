"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from safemeal.shared.contracts.semantic import ConstraintStatement
from safemeal.shared.types import JsonObject


class ResolvedConstraints(BaseModel):

    model_config = ConfigDict(extra="forbid")
    hard_safety: tuple[ConstraintStatement, ...] = ()
    strong_requirements: tuple[ConstraintStatement, ...] = ()
    soft_preferences: tuple[ConstraintStatement, ...] = ()
    menu_goals: tuple[ConstraintStatement, ...] = ()

    @property
    def active(self) -> tuple[ConstraintStatement, ...]:
        return (
            *self.hard_safety,
            *self.strong_requirements,
            *self.soft_preferences,
            *self.menu_goals,
        )


class ToolEvidence(BaseModel):

    model_config = ConfigDict(extra="forbid")
    recipe_name: str = Field(min_length=1, max_length=255)
    ingredients: tuple[str, ...] = ()
    ingredients_complete: bool = False
    categories: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    source: str = ""
    source_complete: bool = False
    fields: JsonObject = Field(default_factory=dict)


class ConstraintDecision(BaseModel):

    model_config = ConfigDict(extra="forbid")
    status: Literal["satisfied", "violated", "unknown"]
    constraint: ConstraintStatement
    recipe_name: str
    reason: str
    matched_terms: tuple[str, ...] = ()
    evidence: ToolEvidence
