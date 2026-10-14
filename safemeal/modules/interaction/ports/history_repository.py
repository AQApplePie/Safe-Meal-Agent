"""单条去重写入与有界历史读取端口。"""

from typing import Protocol
from safemeal.modules.interaction.contracts.models import InteractionActor
from safemeal.modules.interaction.contracts.history import HistoryEntry, HistoryPosition


# 类说明（接口类）：HistoryRepository
# 作用：定义浏览历史仓储接口的能力契约，供应用层与具体实现解耦。
class HistoryRepository(Protocol):
    # 方法说明：record
    # 作用：向浏览历史仓储接口记录本次操作的结果和状态。
    # 入参：
    #   recipe_id（int）：目标食谱的整数标识。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    # 出参：HistoryEntry；浏览历史条目。
    def record(self, recipe_id: int, actor: InteractionActor) -> HistoryEntry: ...
    # 方法说明：list_recent
    # 作用：读取当前用户最近浏览的食谱及时间。
    # 入参：
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    #   limit（int）：本次查询或处理的最大条目数。
    #   before（HistoryPosition | None）：查询的上界或检查点游标。
    # 出参：tuple[HistoryEntry, ...]；浏览历史条目组成的元组。
    def list_recent(
        self, actor: InteractionActor, limit: int, before: HistoryPosition | None
    ) -> tuple[HistoryEntry, ...]: ...
