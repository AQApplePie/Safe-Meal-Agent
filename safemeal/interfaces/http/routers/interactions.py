"""食谱点赞/收藏接口；身份仅来自现有认证依赖。"""

from fastapi import APIRouter, Depends, Path, Request
from starlette.concurrency import run_in_threadpool
from safemeal.interfaces.http.authentication import get_interaction_actor
from safemeal.interfaces.http.platform_dependencies import get_interaction_service
from safemeal.modules.interaction.application.interaction_service import (
    InteractionService,
)
from safemeal.modules.interaction.contracts.models import (
    InteractionActor,
    RecipeInteraction,
)

router = APIRouter()


# 方法说明：read_interaction
# 作用：读取当前用户对指定食谱的点赞与收藏状态。
# 入参：
#   recipe_id（int）：目标食谱的整数标识；默认值为 Path(gt=0)。
#   actor（InteractionActor）：包含租户与用户标识的行为操作主体；由 FastAPI 依赖注入。
#   service（InteractionService）：点赞收藏业务服务；由 FastAPI 依赖注入。
# 出参：RecipeInteraction；用户食谱交互状态与计数。
@router.get("/{recipe_id}/interaction", response_model=RecipeInteraction)
async def read_interaction(
    recipe_id: int = Path(gt=0),
    actor: InteractionActor = Depends(get_interaction_actor),
    service: InteractionService = Depends(get_interaction_service),
) -> RecipeInteraction:
    return await run_in_threadpool(
        service.read,
        recipe_id,
        actor,
    )


# 方法说明：set_like
# 作用：设置当前用户对指定食谱的目标点赞状态。
# 入参：
#   request（Request）：HTTP 请求或应用层请求契约。
#   recipe_id（int）：目标食谱的整数标识；默认值为 Path(gt=0)。
#   actor（InteractionActor）：包含租户与用户标识的行为操作主体；由 FastAPI 依赖注入。
#   service（InteractionService）：点赞收藏业务服务；由 FastAPI 依赖注入。
# 出参：RecipeInteraction；用户食谱交互状态与计数。
@router.put("/{recipe_id}/like", response_model=RecipeInteraction)
@router.delete("/{recipe_id}/like", response_model=RecipeInteraction)
async def set_like(
    request: Request,
    recipe_id: int = Path(gt=0),
    actor: InteractionActor = Depends(get_interaction_actor),
    service: InteractionService = Depends(get_interaction_service),
) -> RecipeInteraction:
    return await run_in_threadpool(
        service.set_state,
        recipe_id,
        actor,
        "like",
        request.method == "PUT",
    )


# 方法说明：set_favorite
# 作用：设置当前用户对指定食谱的目标收藏状态。
# 入参：
#   request（Request）：HTTP 请求或应用层请求契约。
#   recipe_id（int）：目标食谱的整数标识；默认值为 Path(gt=0)。
#   actor（InteractionActor）：包含租户与用户标识的行为操作主体；由 FastAPI 依赖注入。
#   service（InteractionService）：点赞收藏业务服务；由 FastAPI 依赖注入。
# 出参：RecipeInteraction；用户食谱交互状态与计数。
@router.put("/{recipe_id}/favorite", response_model=RecipeInteraction)
@router.delete("/{recipe_id}/favorite", response_model=RecipeInteraction)
async def set_favorite(
    request: Request,
    recipe_id: int = Path(gt=0),
    actor: InteractionActor = Depends(get_interaction_actor),
    service: InteractionService = Depends(get_interaction_service),
) -> RecipeInteraction:
    return await run_in_threadpool(
        service.set_state,
        recipe_id,
        actor,
        "favorite",
        request.method == "PUT",
    )
