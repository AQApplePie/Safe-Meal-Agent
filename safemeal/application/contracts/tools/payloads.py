"""定义跨层传递的稳定数据契约。"""

from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator
from safemeal.shared.types import JsonObject
from safemeal.application.contracts.dietary_safety.constraints import RecipeSafetyRecord
from safemeal.application.contracts.dietary_safety.control_plane import (
    ConstraintDecision,
)
from safemeal.application.contracts.workflow.semantic import ConstraintStatement


class DietarySafeRecipeQueryArgs(BaseModel):
    """饮食忌口/过敏安全查询参数。"""

    excluded_ingredients: list[str] = Field(
        min_length=1,
        description="需要硬排除的忌口/过敏食材，例如 ['鸡蛋', '扇贝']。",
    )
    target_dish: Optional[str] = Field(
        default=None,
        description="需要判断是否适合的指定菜名；为空时返回安全推荐和排除样例。",
    )
    recommend_limit: int = Field(
        default=2,
        ge=0,
        le=10,
        description="需要返回的安全推荐数量。",
    )
    excluded_limit: int = Field(
        default=5,
        ge=0,
        le=20,
        description="需要返回的命中禁忌食材菜品数量。",
    )


class KnowledgeSearchResult(BaseModel):

    query: str
    documents: list[JsonObject] = Field(default_factory=list)
    count: int


class KnowledgeSearchArgs(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    filter_expr: Optional[str] = None


class DietarySafeRecipeQueryResult(BaseModel):
    """忌口/过敏专用查询工具返回值。"""

    database: str = "neo4j"
    query_type: str = "dietary_safe_recipe_query"
    target_dish: Optional[str] = None
    excluded_ingredients: list[str] = Field(default_factory=list)
    expanded_excluded_ingredients: list[str] = Field(default_factory=list)
    safe_recipes: list[RecipeSafetyRecord] = Field(default_factory=list)
    excluded_recipes: list[RecipeSafetyRecord] = Field(default_factory=list)
    unknown_recipes: list[RecipeSafetyRecord] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class GetRecipeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: int = Field(gt=0)


class VerifyRecipeConstraintsArgs(BaseModel):

    model_config = ConfigDict(extra="forbid")
    recipe_ids: list[int] = Field(min_length=1, max_length=20)
    constraints: list[ConstraintStatement] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_unique_recipe_ids(self) -> "VerifyRecipeConstraintsArgs":
        if len(self.recipe_ids) != len(set(self.recipe_ids)):
            raise ValueError("recipe_ids must be unique")
        return self


class RecipeConstraintVerificationResult(BaseModel):

    verified: bool
    recipe_count: int
    decisions: list[ConstraintDecision]
