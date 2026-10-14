"""事务内读取与设置交互目标状态的持久化端口。"""

from typing import Protocol
from safemeal.modules.interaction.contracts.behavior import FavoriteEntry
from safemeal.modules.interaction.contracts.models import (
    InteractionActor,
    ReactionKind,
    RecipeInteraction,
)


# 类说明（接口类）：ReactionRepository
# 作用：定义点赞收藏事实仓储接口的能力契约，供应用层与具体实现解耦。
class ReactionRepository(Protocol):
    # 方法说明：read
    # 作用：通过点赞收藏事实仓储接口读取目标记录或当前状态。
    # 入参：
    #   recipe_id（int）：目标食谱的整数标识。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    # 出参：RecipeInteraction；用户食谱交互状态与计数。
    def read(self, recipe_id: int, actor: InteractionActor) -> RecipeInteraction: ...
    # 方法说明：set_state
    # 作用：在同一事务中设置目标点赞或收藏状态，并追加行为事件。
    # 入参：
    #   recipe_id（int）：目标食谱的整数标识。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    #   kind（ReactionKind）：当前业务记录或操作的类型。
    #   enabled（bool）：目标行为或功能是否启用。
    # 出参：RecipeInteraction；用户食谱交互状态与计数。
    def set_state(
        self, recipe_id: int, actor: InteractionActor, kind: ReactionKind, enabled: bool
    ) -> RecipeInteraction: ...

    # 方法说明：read_many
    # 作用：批量读取食谱交互状态，避免逐条查询。
    # 入参：
    #   recipe_ids（tuple[int, ...]）：待查询或校验的食谱标识集合。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    # 出参：tuple[RecipeInteraction, ...]；用户食谱交互状态与计数组成的元组。
    def read_many(
        self, recipe_ids: tuple[int, ...], actor: InteractionActor
    ) -> tuple[RecipeInteraction, ...]: ...
    # 方法说明：list_favorites
    # 作用：分页读取当前用户收藏的食谱。
    # 入参：
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    #   offset（int）：本次分页跳过的记录数量。
    #   limit（int）：本次查询或处理的最大条目数。
    # 出参：tuple[FavoriteEntry, ...]；收藏食谱条目组成的元组。
    def list_favorites(
        self, actor: InteractionActor, offset: int, limit: int
    ) -> tuple[FavoriteEntry, ...]: ...
