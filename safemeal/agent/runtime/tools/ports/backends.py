"""定义应用层依赖的能力端口。"""

from typing import Protocol
from safemeal.agent.runtime.tools.contracts.payloads import DietarySafeRecipeQueryResult


# 类说明（接口类）：DietarySearch
# 作用：定义安全食谱检索接口的能力契约，供应用层与具体实现解耦。
class DietarySearch(Protocol):
    # 方法说明：search
    # 作用：通过安全食谱检索接口按查询条件检索候选及其证据。
    # 入参：
    #   excluded_ingredients（list[str]）：必须排除的食材集合。
    #   target_dish（str | None）：本轮要查询、替换或审核的目标菜品。
    #   recommend_limit（int）：最多推荐的菜品数。
    #   excluded_limit（int）：最多读取的排除记录数。
    # 出参：DietarySafeRecipeQueryResult；图安全食谱查询工具结果。
    def search(
        self,
        *,
        excluded_ingredients: list[str],
        target_dish: str | None,
        recommend_limit: int,
        excluded_limit: int,
    ) -> DietarySafeRecipeQueryResult: ...
