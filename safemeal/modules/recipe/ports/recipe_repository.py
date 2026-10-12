"""定义应用层依赖的能力端口。"""

from __future__ import annotations

from typing import Protocol

from safemeal.modules.recipe.contracts.catalog import (
    RecipeQuery,
    RecipeSearchResult,
)
from safemeal.modules.recipe.contracts.models import Recipe


# 类说明（接口类）：RecipeRepository
# 作用：定义食谱仓储接口的能力契约，供应用层与具体实现解耦。
class RecipeRepository(Protocol):
    # 方法说明：search
    # 作用：通过食谱仓储接口按查询条件检索候选及其证据。
    # 入参：
    #   query（RecipeQuery）：食谱筛选与推荐查询。
    # 出参：RecipeSearchResult；食谱查询与推荐结果。
    def search(self, query: RecipeQuery) -> RecipeSearchResult: ...

    # 方法说明：get
    # 作用：通过食谱仓储接口读取指定标识对应的业务对象。
    # 入参：
    #   recipe_id（int）：目标食谱的整数标识。
    # 出参：Recipe | None；完整食谱业务模型或None（未取得结果）。
    def get(self, recipe_id: int) -> Recipe | None: ...


__all__ = ["RecipeRepository"]
