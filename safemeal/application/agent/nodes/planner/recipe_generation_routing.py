"""Deterministic intent routing for recipe-generation requests."""


def is_recipe_generation_request(question: str) -> bool:
    normalized = question.casefold()
    recipe_terms = ("菜谱", "食谱", "配方", "一道菜")
    generation_terms = ("生成", "设计", "创作", "制定", "原创", "新菜")
    return any(term in normalized for term in recipe_terms) and any(
        term in normalized for term in generation_terms
    )


__all__ = ["is_recipe_generation_request"]
