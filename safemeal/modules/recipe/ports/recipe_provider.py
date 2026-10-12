"""定义应用层依赖的能力端口。"""

from typing import Protocol

from safemeal.modules.recipe.contracts.lookup import RecipeLookupResult


# 类说明（接口类）：RecipeProvider
# 作用：定义外部菜谱查找接口的能力契约，供应用层与具体实现解耦。
class RecipeProvider(Protocol):
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：str。
    name: str

    # 方法说明：lookup
    # 作用：从配置的菜谱来源查找目标菜品及其食材证据。
    # 入参：
    #   recipe_name（str）：目标菜谱名称。
    # 出参：RecipeLookupResult；外部或本地菜谱查找结果。
    def lookup(self, recipe_name: str) -> RecipeLookupResult: ...
