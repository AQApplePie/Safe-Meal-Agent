"""菜谱模块依赖的生成能力端口。"""

from typing import Protocol

from safemeal.modules.recipe.contracts.generated import GeneratedRecipe
from safemeal.modules.recipe.contracts.generation import RecipeGenerationRequest


# 类说明（接口类）：RecipeGenerator
# 作用：生成菜谱所需的最小能力，不绑定 Agent 或具体模型实现。
class RecipeGenerator(Protocol):
    """生成菜谱所需的最小能力，不绑定 Agent 或具体模型实现。"""

    # 方法说明：generate_recipe
    # 作用：根据结构化生成要求调用模型，校验生成菜谱。
    # 入参：
    #   request（RecipeGenerationRequest）：结构化食谱生成请求。
    # 出参：GeneratedRecipe；模型生成菜谱。
    async def generate_recipe(
        self,
        request: RecipeGenerationRequest,
    ) -> GeneratedRecipe: ...


__all__ = ["RecipeGenerator"]
