"""租户内今日热门与最受欢迎榜单。"""

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool
from safemeal.interfaces.http.authentication import get_interaction_actor
from safemeal.interfaces.http.platform_dependencies import get_ranking_service
from safemeal.modules.interaction.application.ranking_service import RankingService
from safemeal.modules.interaction.contracts.models import InteractionActor
from safemeal.modules.interaction.contracts.ranking import RankingMode, RankingPage

router = APIRouter()


# 方法说明：list_rankings
# 作用：读取指定模式和日期的热门食谱榜单。
# 入参：
#   mode（RankingMode）：当前榜单或运行模式；默认值为 Query(default='today')。
#   offset（int）：本次分页跳过的记录数量；默认值为 Query(default=0, ge=0, le=9999)。
#   limit（int）：本次查询或处理的最大条目数；默认值为 Query(default=20, ge=1, le=50)。
#   actor（InteractionActor）：包含租户与用户标识的行为操作主体；由 FastAPI 依赖注入。
#   service（RankingService）：热门榜单读取与重建服务；由 FastAPI 依赖注入。
# 出参：RankingPage；榜单分页响应。
@router.get("/rankings", response_model=RankingPage)
async def list_rankings(
    mode: RankingMode = Query(default="today"),
    offset: int = Query(default=0, ge=0, le=9999),
    limit: int = Query(default=20, ge=1, le=50),
    actor: InteractionActor = Depends(get_interaction_actor),
    service: RankingService = Depends(get_ranking_service),
) -> RankingPage:
    return await run_in_threadpool(service.read, actor.tenant_id, mode, offset, limit)
