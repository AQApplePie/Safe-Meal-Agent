"""显式浏览上报和本人最近浏览列表。"""

from fastapi import APIRouter, Depends, Path, Query
from starlette.concurrency import run_in_threadpool
from safemeal.interfaces.http.authentication import get_interaction_actor
from safemeal.interfaces.http.platform_dependencies import get_history_service
from safemeal.modules.interaction.application.history_service import HistoryService
from safemeal.modules.interaction.contracts.history import HistoryEntry, HistoryPage
from safemeal.modules.interaction.contracts.models import InteractionActor

router = APIRouter()


# 方法说明：record_view
# 作用：记录当前用户的一次食谱浏览行为。
# 入参：
#   recipe_id（int）：目标食谱的整数标识；默认值为 Path(gt=0, le=2147483647)。
#   actor（InteractionActor）：包含租户与用户标识的行为操作主体；由 FastAPI 依赖注入。
#   service（HistoryService）：浏览历史业务服务；由 FastAPI 依赖注入。
# 出参：HistoryEntry；浏览历史条目。
@router.put("/{recipe_id}/view", response_model=HistoryEntry)
async def record_view(
    recipe_id: int = Path(gt=0, le=2147483647),
    actor: InteractionActor = Depends(get_interaction_actor),
    service: HistoryService = Depends(get_history_service),
) -> HistoryEntry:
    return await run_in_threadpool(service.record, recipe_id, actor)


# 方法说明：list_history
# 作用：按游标分页读取当前用户最近浏览历史。
# 入参：
#   limit（int）：本次查询或处理的最大条目数；默认值为 Query(default=20, ge=1, le=50)。
#   cursor（str | None）：下一页起始位置的游标；默认值为 Query(default=None, min_length=1,
# max_length=256)。
#   actor（InteractionActor）：包含租户与用户标识的行为操作主体；由 FastAPI 依赖注入。
#   service（HistoryService）：浏览历史业务服务；由 FastAPI 依赖注入。
# 出参：HistoryPage；浏览历史游标分页结果。
@router.get("/history", response_model=HistoryPage)
async def list_history(
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, min_length=1, max_length=256),
    actor: InteractionActor = Depends(get_interaction_actor),
    service: HistoryService = Depends(get_history_service),
) -> HistoryPage:
    return await run_in_threadpool(service.list_recent, actor, limit, cursor)
