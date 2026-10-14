"""点赞和收藏用例；不依赖 HTTP、SQL、缓存或 Agent。"""

from safemeal.modules.interaction.contracts.models import (
    InteractionActor,
    ReactionKind,
    RecipeInteraction,
)
from safemeal.modules.interaction.ports.reaction_repository import ReactionRepository
from safemeal.modules.interaction.contracts.behavior import (
    BatchInteractionResponse,
    FavoritePage,
)
from safemeal.shared.exceptions import InputValidationError


# 类说明（业务或基础设施实现类）：InteractionService
# 作用：实现点赞收藏业务服务，封装该组件的业务处理与依赖协作。
class InteractionService:
    # 方法说明：__init__
    # 作用：初始化点赞收藏业务服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   repository（ReactionRepository）：当前业务依赖的仓储实现。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, repository: ReactionRepository) -> None:
        # 实例属性说明：_repository
        # 作用：当前业务依赖的仓储实现。
        self._repository = repository

    # 方法说明：_validate
    # 作用：在点赞收藏业务服务内部校验配置或输入结构。
    # 入参：
    #   recipe_id（int）：目标食谱的整数标识。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    @staticmethod
    def _validate(recipe_id: int) -> None:
        if recipe_id <= 0:
            raise InputValidationError("Recipe id must be positive")

    # 方法说明：read
    # 作用：通过点赞收藏业务服务读取目标记录或当前状态。
    # 入参：
    #   recipe_id（int）：目标食谱的整数标识。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    # 出参：RecipeInteraction；用户食谱交互状态与计数。
    def read(self, recipe_id: int, actor: InteractionActor) -> RecipeInteraction:
        self._validate(recipe_id)
        return self._repository.read(recipe_id, actor)

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
    ) -> RecipeInteraction:
        self._validate(recipe_id)
        if kind not in ("like", "favorite"):
            raise InputValidationError("Unknown reaction kind")
        return self._repository.set_state(recipe_id, actor, kind, enabled)

    # 方法说明：read_many
    # 作用：批量读取食谱交互状态，避免逐条查询。
    # 入参：
    #   recipe_ids（tuple[int, ...]）：待查询或校验的食谱标识集合。
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    # 出参：BatchInteractionResponse；批量食谱交互查询响应。
    def read_many(
        self, recipe_ids: tuple[int, ...], actor: InteractionActor
    ) -> BatchInteractionResponse:
        if not 1 <= len(recipe_ids) <= 100 or any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or not 1 <= item <= 2147483647
            for item in recipe_ids
        ):
            raise InputValidationError("Provide 1–100 valid recipe ids")
        unique = tuple(dict.fromkeys(recipe_ids))
        found = {
            item.recipe_id: item for item in self._repository.read_many(unique, actor)
        }
        return BatchInteractionResponse(
            items=tuple(found[item] for item in unique if item in found),
            missing_recipe_ids=tuple(item for item in unique if item not in found),
        )

    # 方法说明：list_favorites
    # 作用：分页读取当前用户收藏的食谱。
    # 入参：
    #   actor（InteractionActor）：包含租户与用户标识的行为操作主体。
    #   offset（int）：本次分页跳过的记录数量；默认值为 0。
    #   limit（int）：本次查询或处理的最大条目数；默认值为 20。
    # 出参：FavoritePage；收藏列表分页结果。
    def list_favorites(
        self, actor: InteractionActor, offset: int = 0, limit: int = 20
    ) -> FavoritePage:
        if not 0 <= offset <= 10000 or not 1 <= limit <= 50:
            raise InputValidationError("Invalid favorites pagination")
        rows = self._repository.list_favorites(actor, offset, limit + 1)
        return FavoritePage(
            items=rows[:limit], offset=offset, limit=limit, has_more=len(rows) > limit
        )
