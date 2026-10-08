"""校验模型生成菜谱是否违反硬安全约束。"""

import re
from collections.abc import Iterable
from safemeal.modules.recipe.contracts.generated import GeneratedRecipe
from safemeal.modules.dietary.application.recipe_safety import (
    match_forbidden_ingredients,
)


def generated_recipe_violations(
    recipe: GeneratedRecipe, forbidden: Iterable[str]
) -> list[str]:
    terms = tuple(forbidden)
    matched = list(
        match_forbidden_ingredients(
            [i.name for i in recipe.ingredients] + list(recipe.allergens), terms
        )
    )
    texts = [
        recipe.description,
        *[i.preparation or "" for i in recipe.ingredients],
        *[s.instruction + "。" + (s.tips or "") for s in recipe.steps],
    ]
    for text in texts:
        for clause in re.split(r"[，。；;,.！!\n]", text):
            for term in terms:
                for hit in re.finditer(re.escape(term), clause):
                    prefix = clause[: hit.start()]

                    if not re.search(
                        r"(?:不要|勿|避免|禁止|无需|不放|不加|不含|不使用|不需要|不能|不得|不可)(?:加入|添加|使用|放入)?\s*$",
                        prefix,
                    ):
                        matched.append(term)
    return list(dict.fromkeys(matched))
