"""公共食谱读取接口；筛选/分页交给已有 RecipeService。"""

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import StringConstraints
from starlette.concurrency import run_in_threadpool

from safemeal.interfaces.http.platform_dependencies import get_recipe_browse_service
from safemeal.modules.recipe.application.recipe_service import RecipeService
from safemeal.modules.recipe.contracts.browsing import RecipeListResponse, RecipeSummary
from safemeal.modules.recipe.contracts.catalog import RecipeQuery, RecipeSortField
from safemeal.modules.recipe.contracts.models import Recipe, RecipeDifficulty
from safemeal.shared.exceptions import StoredDataIntegrityError

router = APIRouter()
IngredientTerm = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


# 方法说明：list_recipes
# 作用：按筛选、排序及分页条件查询食谱列表。
# 入参：
#   service（RecipeService）：食谱查询推荐与生成业务服务；由 FastAPI 依赖注入。
#   name（str | None）：当前对象或字段的名称；默认值为 Query(default=None, min_length=1,
# max_length=255)。
#   cuisine（str | None）：食谱菜系筛选条件；默认值为 Query(default=None, min_length=1,
# max_length=255)。
#   difficulties（list[RecipeDifficulty]）：允许的食谱难度集合；默认值为 Query(default=[],
# max_length=3)。
#   include_ingredients（list[IngredientTerm]）：查询结果必须包含的食材词项集合；默认值为
# Query(default=[], max_length=20)。
#   exclude_ingredients（list[IngredientTerm]）：必须排除的食材集合；默认值为 Query(default=[],
# max_length=50)。
#   max_total_time_minutes（int | None）：食谱制作总时长上限，单位分钟；默认值为 Query(default=None,
# ge=0, le=10080)。
#   max_calories（Decimal | None）：食谱热量上限；默认值为 Query(default=None, ge=0,
# le=100000)。
#   sort_by（RecipeSortField）：食谱排序字段；默认值为 Query(default=RecipeSortField.NAME)。
#   sort_order（Literal['asc', 'desc']）：升序或降序排序方向；默认值为 Query(default='asc')。
#   offset（int）：本次分页跳过的记录数量；默认值为 Query(default=0, ge=0, le=100000)。
#   limit（int）：本次查询或处理的最大条目数；默认值为 Query(default=10, ge=1, le=50)。
# 出参：RecipeListResponse；食谱列表分页响应。
@router.get("", response_model=RecipeListResponse)
async def list_recipes(
    service: RecipeService = Depends(get_recipe_browse_service),
    name: str | None = Query(default=None, min_length=1, max_length=255),
    cuisine: str | None = Query(default=None, min_length=1, max_length=255),
    difficulties: list[RecipeDifficulty] = Query(default=[], max_length=3),
    include_ingredients: list[IngredientTerm] = Query(default=[], max_length=20),
    exclude_ingredients: list[IngredientTerm] = Query(default=[], max_length=50),
    max_total_time_minutes: int | None = Query(default=None, ge=0, le=10080),
    max_calories: Decimal | None = Query(default=None, ge=0, le=100000),
    sort_by: RecipeSortField = Query(default=RecipeSortField.NAME),
    sort_order: Literal["asc", "desc"] = Query(default="asc"),
    offset: int = Query(default=0, ge=0, le=100000),
    limit: int = Query(default=10, ge=1, le=50),
) -> RecipeListResponse:
    result = await run_in_threadpool(
        service.search,
        RecipeQuery(
            name_contains=name,
            cuisine=cuisine,
            difficulties=tuple(difficulties),
            include_ingredients=tuple(include_ingredients),
            exclude_ingredients=tuple(exclude_ingredients),
            max_total_time_minutes=max_total_time_minutes,
            max_calories=max_calories,
            sort_by=sort_by,
            sort_order=sort_order,
            offset=offset,
            limit=limit,
        ),
    )
    canonical_recipes = [item for item in result.items if isinstance(item, Recipe)]
    if len(canonical_recipes) != len(result.items):
        raise StoredDataIntegrityError(
            "Public recipe browsing requires canonical catalog records"
        )
    return RecipeListResponse(
        items=tuple(
            RecipeSummary(
                id=item.id,
                name=item.name,
                description=item.description,
                total_time_minutes=item.total_time_minutes,
                servings=item.servings,
                difficulty=item.difficulty,
                cuisine=item.cuisine,
                calories=item.nutrition.calories,
            )
            for item in canonical_recipes
        ),
        total=result.total,
        offset=result.offset,
        limit=result.limit,
        has_more=result.offset + len(result.items) < result.total,
    )


# 方法说明：get_recipe
# 作用：读取并返回指定食谱的完整详情。
# 入参：
#   recipe_id（int）：目标食谱的整数标识；默认值为 Path(gt=0)。
#   service（RecipeService）：食谱查询推荐与生成业务服务；由 FastAPI 依赖注入。
# 出参：Recipe；完整食谱业务模型。
@router.get("/{recipe_id}", response_model=Recipe)
async def get_recipe(
    recipe_id: int = Path(gt=0),
    service: RecipeService = Depends(get_recipe_browse_service),
) -> Recipe:
    return await run_in_threadpool(service.get, recipe_id)
