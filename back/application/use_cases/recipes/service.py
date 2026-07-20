"""Application use cases for structured recipe reads and recommendations."""

from __future__ import annotations

from SafeMealAgent.back.application.domain.recipe_policy import RecipePolicy
from SafeMealAgent.back.application.domain.recipes import Recipe, RecipeQuery, RecipeSearchResult
from SafeMealAgent.back.application.errors import BusinessConstraintError, ResourceNotFoundError
from SafeMealAgent.back.application.ports.recipe_repository import RecipeRepository


class RecipeService:
    _MAX_RECOMMENDATION_CANDIDATES = 1000

    def __init__(
        self, repository: RecipeRepository, policy: RecipePolicy | None = None
    ) -> None:
        self._repository = repository
        self._policy = policy or RecipePolicy()

    def search(self, query: RecipeQuery) -> RecipeSearchResult:
        return self._repository.search(query)

    def get(self, recipe_id: int) -> Recipe:
        recipe = self._repository.get(recipe_id)
        if recipe is None:
            raise ResourceNotFoundError("Recipe not found")
        return recipe

    def recommend(self, query: RecipeQuery) -> RecipeSearchResult:
        page_size = 50
        candidate_items: list[Recipe] = []
        scanned = 0
        total = None
        while total is None or scanned < total:
            page = self._repository.search(
                query.model_copy(
                    update={
                        "dietary_types": (),
                        "offset": scanned,
                        "limit": page_size,
                    }
                )
            )
            total = page.total
            if total > self._MAX_RECOMMENDATION_CANDIDATES:
                raise BusinessConstraintError(
                    "Recommendation query is too broad; add deterministic filters"
                )
            candidate_items.extend(page.items)
            scanned += len(page.items)
            if not page.items:
                break
        allowed = self._policy.filter(
            candidate_items,
            excluded_ingredients=query.exclude_ingredients,
            dietary_types=query.dietary_types,
        )
        selected = allowed[query.offset : query.offset + query.limit]
        return RecipeSearchResult(
            items=selected,
            total=len(allowed),
            offset=query.offset,
            limit=query.limit,
        )


__all__ = ["RecipeService"]
