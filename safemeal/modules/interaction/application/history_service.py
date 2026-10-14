"""浏览历史用例；游标仅表示排序位置，不携带身份。"""

from base64 import b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from pydantic import ValidationError
from safemeal.modules.interaction.contracts.history import (
    HistoryPage,
    HistoryPosition,
    HistoryEntry,
)
from safemeal.modules.interaction.contracts.models import InteractionActor
from safemeal.modules.interaction.ports.history_repository import HistoryRepository
from safemeal.shared.exceptions import InputValidationError


# 类说明（业务或基础设施实现类）：HistoryService
# 作用：实现浏览历史业务服务，封装该组件的业务处理与依赖协作。
class HistoryService:
    # 方法说明：__init__
    # 作用：初始化浏览历史业务服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   repository（HistoryRepository）：当前业务依赖的仓储实现。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, repository: HistoryRepository) -> None:
        # 实例属性说明：_repository
        # 作用：当前业务依赖的仓储实现。
        self._repository = repository

    # 方法说明：record
    # 作用：向浏览历史业务服务记录本次操作的结果和状态。
    # 入参：
    #   recipe_id（int）：目标食谱的整数标识。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    # 出参：HistoryEntry；浏览历史条目。
    def record(self, recipe_id: int, actor: InteractionActor) -> HistoryEntry:
        if not 1 <= recipe_id <= 2147483647:
            raise InputValidationError("Recipe id must be between 1 and 2147483647")
        return self._repository.record(recipe_id, actor)

    # 方法说明：list_recent
    # 作用：读取当前用户最近浏览的食谱及时间。
    # 入参：
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    #   limit（int）：本次查询或处理的最大条目数；默认值为 20。
    #   cursor（str | None）：下一页起始位置的游标；默认值为 None。
    # 出参：HistoryPage；浏览历史游标分页结果。
    def list_recent(
        self, actor: InteractionActor, limit: int = 20, cursor: str | None = None
    ) -> HistoryPage:
        if not 1 <= limit <= 50:
            raise InputValidationError("History limit must be between 1 and 50")
        before = None
        if cursor is not None:
            try:
                if not cursor or len(cursor) > 256:
                    raise ValueError("Invalid cursor size")
                payload = b64decode(cursor, altchars=b"-_", validate=True)
                before = HistoryPosition.model_validate_json(payload)
            except (ValueError, Base64Error, ValidationError) as exc:
                raise InputValidationError("Invalid history cursor") from exc
        rows = self._repository.list_recent(actor, limit + 1, before)
        items = rows[:limit]
        has_more = len(rows) > limit
        next_cursor = None
        if has_more:
            last = items[-1]
            position = HistoryPosition(
                last_viewed_at=last.last_viewed_at, recipe_id=last.recipe_id
            )
            next_cursor = urlsafe_b64encode(
                position.model_dump_json().encode()
            ).decode()
        return HistoryPage(items=items, has_more=has_more, next_cursor=next_cursor)
