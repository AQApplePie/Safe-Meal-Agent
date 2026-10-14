"""本人收藏列表与批量交互状态，身份仅来自认证依赖。"""

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool
from safemeal.interfaces.http.authentication import get_interaction_actor
from safemeal.interfaces.http.platform_dependencies import get_interaction_service
from safemeal.modules.interaction.application.interaction_service import (
    InteractionService,
)
from safemeal.modules.interaction.contracts.models import InteractionActor
from safemeal.modules.interaction.contracts.behavior import (
    BatchInteractionQuery,
    BatchInteractionResponse,
    FavoritePage,
)

router = APIRouter()


# 方法说明：list_favorites
# 作用：分页读取当前用户收藏的食谱。
# 入参：
#   offset（int）：本次分页跳过的记录数量；默认值为 Query(default=0, ge=0, le=10000)。
#   limit（int）：本次查询或处理的最大条目数；默认值为 Query(default=20, ge=1, le=50)。
#   actor（InteractionActor）：包含租户与用户标识的行为操作主体；由 FastAPI 依赖注入。
#   service（InteractionService）：点赞收藏业务服务；由 FastAPI 依赖注入。
# 出参：FavoritePage；收藏列表分页结果。
@router.get("/favorites", response_model=FavoritePage)
async def list_favorites(
    offset: int = Query(default=0, ge=0, le=10000),
    limit: int = Query(default=20, ge=1, le=50),
    actor: InteractionActor = Depends(get_interaction_actor),
    service: InteractionService = Depends(get_interaction_service),
) -> FavoritePage:
    return await run_in_threadpool(service.list_favorites, actor, offset, limit)


# 方法说明：query_interactions
# 作用：批量查询当前用户对多个食谱的交互状态。
# 入参：
#   request（BatchInteractionQuery）：批量食谱交互查询请求。
#   actor（InteractionActor）：包含租户与用户标识的行为操作主体；由 FastAPI 依赖注入。
#   service（InteractionService）：点赞收藏业务服务；由 FastAPI 依赖注入。
# 出参：BatchInteractionResponse；批量食谱交互查询响应。
@router.post("/interactions/query", response_model=BatchInteractionResponse)
async def query_interactions(
    request: BatchInteractionQuery,
    actor: InteractionActor = Depends(get_interaction_actor),
    service: InteractionService = Depends(get_interaction_service),
) -> BatchInteractionResponse:
    return await run_in_threadpool(service.read_many, tuple(request.recipe_ids), actor)
