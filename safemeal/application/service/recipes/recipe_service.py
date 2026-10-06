"""食谱查询、推荐与生成的统一业务服务。"""

from __future__ import annotations

from safemeal.application.service.recipes.dietary_filter import DietaryRecipeFilter
from safemeal.application.contracts.recipes.catalog import (
    RecipeQuery,
    RecipeSearchResult,
)
from safemeal.application.contracts.recipes.models import Recipe
from safemeal.application.contracts.recipes.lookup import RecipeCandidate
from safemeal.application.contracts.recipes.lookup import MenuRecipeCandidate
from safemeal.application.ports.recipes.recipe_provider import RecipeProvider
from safemeal.application.exceptions import (
    BusinessConstraintError,
    FeatureUnavailableError,
    ResourceNotFoundError,
)
from safemeal.application.ports.persistence.recipe_repository import RecipeRepository


from safemeal.application.contracts.recipes.generation import RecipeGenerationRequest
from safemeal.application.contracts.recipes.generated import GeneratedRecipe
from safemeal.application.service.dietary_safety.generated_safety import (
    generated_recipe_violations,
)
from safemeal.application.service.dietary_safety.recipe_safety import (
    ingredient_matches_forbidden_term,
)
from safemeal.application.exceptions import ModelOutputValidationError
from safemeal.application.agent.model import AgentModelGateway
from safemeal.application.service.recipes.classification import classify_recipe
from safemeal.application.service.recipes.food_category import recipe_matches_category


class RecipeService:
    _MAX_RECOMMENDATION_CANDIDATES = 1000

    def __init__(
        self,
        repository: RecipeRepository,
        model_gateway: AgentModelGateway | None = None,
        recipe_filter: DietaryRecipeFilter | None = None,
        lookup_providers: tuple[RecipeProvider, ...] = (),
    ) -> None:
        self._model_gateway = model_gateway
        self._repository = repository
        self._recipe_filter = recipe_filter or DietaryRecipeFilter()
        self._lookup_providers = lookup_providers

    @staticmethod
    def _normalize_name(value: str) -> str:
        return "".join(
            character for character in value.casefold() if character.isalnum()
        )

    @staticmethod
    def _canonical_candidate(recipe: Recipe) -> RecipeCandidate:
        return RecipeCandidate(
            name=recipe.name,
            ingredients=tuple(
                {
                    "name": item.ingredient.name,
                    "amount": f"{item.quantity}{item.unit}",
                    "section": item.ingredient_type,
                }
                for item in recipe.ingredients
            ),
            steps="\n".join(step.instruction for step in recipe.steps),
            nutrition=recipe.nutrition.model_dump(mode="json"),
            total_time_minutes=recipe.total_time_minutes,
            servings=recipe.servings,
            source_type="canonical_database",
            source_title=f"recipe:{recipe.id}",
            confidence=1.0,
            persistent=True,
            ingredients_complete=bool(recipe.ingredients),
        )

    @staticmethod
    def _missing_fields(
        candidate: RecipeCandidate, required_fields: tuple[str, ...]
    ) -> tuple[str, ...]:
        missing: list[str] = []
        for field in required_fields:
            available = {
                "ingredients": bool(candidate.ingredients),
                "steps": bool(candidate.steps.strip()),
                "time": candidate.total_time_minutes is not None,
                "nutrition": candidate.nutrition is not None,
            }[field]
            if not available:
                missing.append(field)
        return tuple(missing)

    def search(self, query: RecipeQuery) -> RecipeSearchResult:
        if query.category is not None:
            return self._search_menu_candidates(query)
        result = self._repository.search(query)
        if not query.exact_name:
            return result.model_copy(
                update={"status": "FOUND" if result.items else "NOT_FOUND"}
            )

        target = self._normalize_name(query.name_contains or "")
        exact = [
            item
            for item in result.items
            if isinstance(item, Recipe) and self._normalize_name(item.name) == target
        ]
        searched_sources = ["canonical_database"]
        if exact:
            candidate = self._canonical_candidate(exact[0])
            missing = self._missing_fields(candidate, query.required_fields)
            return RecipeSearchResult(
                items=(candidate,),
                total=1,
                offset=0,
                limit=query.limit,
                status="FIELD_MISSING" if missing else "FOUND",
                missing_fields=missing,
                query=query.name_contains,
                exact_name=True,
                match_type="exact",
                searched_sources=tuple(searched_sources),
            )

        errors: list[str] = []
        for provider in self._lookup_providers:
            searched_sources.append(provider.name)
            provider_result = provider.lookup(query.name_contains or "")
            if provider_result.status == "FOUND" and provider_result.items:
                candidate = provider_result.items[0]
                missing = self._missing_fields(candidate, query.required_fields)
                return RecipeSearchResult(
                    items=(candidate,),
                    total=len(provider_result.items),
                    offset=0,
                    limit=query.limit,
                    status="FIELD_MISSING" if missing else "FOUND",
                    missing_fields=missing,
                    query=query.name_contains,
                    exact_name=True,
                    match_type=provider_result.match_type,
                    searched_sources=tuple(searched_sources),
                    errors=tuple(errors),
                )
            if provider_result.status == "ERROR":
                errors.append(
                    f"{provider.name}: {provider_result.error or 'provider error'}"
                )
        return RecipeSearchResult(
            items=(),
            total=0,
            offset=0,
            limit=query.limit,
            status="ERROR" if errors else "NOT_FOUND",
            query=query.name_contains,
            exact_name=True,
            searched_sources=tuple(searched_sources),
            errors=tuple(errors),
        )

    @staticmethod
    def _menu_candidate(recipe: Recipe) -> MenuRecipeCandidate:
        ingredients = tuple(item.ingredient.name for item in recipe.ingredients)
        main = tuple(
            item.ingredient.name
            for item in recipe.ingredients
            if item.is_main
        ) or tuple(item.ingredient.name for item in recipe.ingredients[:3])
        return MenuRecipeCandidate(
            id=recipe.id,
            name=recipe.name,
            categories=classify_recipe(recipe),
            main_ingredients=main,
            ingredients=ingredients,
            ingredients_complete=bool(ingredients),
            source_type="canonical_database",
            source_title=f"recipe:{recipe.id}",
        )

    def _search_menu_candidates(self, query: RecipeQuery) -> RecipeSearchResult:

        selected: list[MenuRecipeCandidate] = []
        seen_names = set(query.exclude_recipe_names)
        scanned = 0
        page_size = 50
        while len(selected) < query.limit and scanned < self._MAX_RECOMMENDATION_CANDIDATES:
            page = self._repository.search(
                query.model_copy(
                    update={
                        "category": None,
                        "candidate_mode": False,
                        "scope": "local",
                        "offset": scanned,
                        "limit": page_size,
                    }
                )
            )
            recipes = [item for item in page.items if isinstance(item, Recipe)]
            for recipe in recipes:
                candidate = self._menu_candidate(recipe)
                if query.category not in candidate.categories:
                    continue
                if candidate.name in seen_names:
                    continue
                seen_names.add(candidate.name)
                selected.append(candidate)
                if len(selected) >= query.limit:
                    break
            scanned += len(page.items)
            if not page.items or scanned >= page.total:
                break

        if query.scope == "all" and len(selected) < query.limit:
            for provider in self._lookup_providers:
                search_candidates = getattr(provider, "search_candidates", None)
                if not callable(search_candidates):
                    continue
                for candidate in search_candidates(
                    category=query.category,
                    exclude_names=frozenset(seen_names),
                    limit=query.limit - len(selected),
                    exclude_ingredients=query.exclude_ingredients,
                ):
                    if candidate.name not in seen_names:
                        seen_names.add(candidate.name)
                        selected.append(candidate)
        return RecipeSearchResult(
            items=tuple(selected),
            total=len(selected),
            offset=0,
            limit=query.limit,
            status="FOUND" if selected else "NOT_FOUND",
            searched_sources=(
                ("canonical_database", "local_json")
                if query.scope == "all"
                else ("canonical_database",)
            ),
        )

    def get(self, recipe_id: int) -> Recipe:
        recipe = self._repository.get(recipe_id)
        if recipe is None:
            raise ResourceNotFoundError("Recipe not found")
        return recipe

    def recommend(self, query: RecipeQuery) -> RecipeSearchResult:
        page_size = 50
        requested_count = query.requested_count or query.limit
        candidate_limit = query.candidate_limit or query.limit
        candidate_items: list[Recipe] = []
        scanned = 0
        total = None
        while (total is None or scanned < total) and scanned < candidate_limit:
            current_limit = min(page_size, candidate_limit - scanned)
            page = self._repository.search(
                query.model_copy(
                    update={
                        "dietary_types": (),
                        "offset": scanned,
                        "limit": current_limit,
                    }
                )
            )
            total = page.total
            if total > self._MAX_RECOMMENDATION_CANDIDATES:
                raise BusinessConstraintError(
                    "Recommendation query is too broad; add deterministic filters"
                )
            candidate_items.extend(
                item for item in page.items if isinstance(item, Recipe)
            )
            scanned += len(page.items)
            if not page.items:
                break
        allowed = self._recipe_filter.filter_recipes(
            candidate_items,
            excluded_ingredients=query.exclude_ingredients,
            dietary_types=query.dietary_types,
        )
        if query.food_categories:
            allowed = [
                recipe
                for recipe in allowed
                if all(
                    recipe_matches_category(recipe, category)
                    for category in query.food_categories
                )
            ]
        if query.exclude_food_categories:
            allowed = [
                recipe
                for recipe in allowed
                if not any(
                    recipe_matches_category(recipe, category)
                    for category in query.exclude_food_categories
                )
            ]
        selected = allowed[query.offset : query.offset + requested_count]
        fulfilled_count = len(selected)
        return RecipeSearchResult(
            items=selected,
            total=len(allowed),
            offset=query.offset,
            limit=candidate_limit,
            requested_count=requested_count,
            fulfilled_count=fulfilled_count,
            status=(
                "FOUND"
                if fulfilled_count >= requested_count
                else "PARTIAL"
                if fulfilled_count
                else "NOT_FOUND"
            ),
        )

    async def generate(self, request: RecipeGenerationRequest) -> GeneratedRecipe:
        if self._model_gateway is None:
            raise FeatureUnavailableError("Recipe generation requires an enabled model")
        recipe = await self._model_gateway.generate_recipe(request)
        forbidden = tuple(
            request.exclude_ingredients
        ) + DietaryRecipeFilter.excluded_terms_for(request.dietary_types)
        if forbidden and generated_recipe_violations(recipe, forbidden):
            raise ModelOutputValidationError(
                "generated recipe violates ingredient constraints"
            )
        missing_required = [
            required
            for required in request.include_ingredients
            if not any(
                ingredient_matches_forbidden_term(item.name, required)
                for item in recipe.ingredients
            )
        ]
        if missing_required:
            raise ModelOutputValidationError(
                "generated recipe omitted required ingredients: "
                + ", ".join(missing_required)
            )
        if request.servings is not None and recipe.servings != request.servings:
            raise ModelOutputValidationError(
                "generated recipe servings do not match request"
            )
        if (
            request.max_total_time_minutes is not None
            and recipe.total_time_minutes > request.max_total_time_minutes
        ):
            raise ModelOutputValidationError(
                "generated recipe exceeds requested time limit"
            )
        return recipe


__all__ = ["RecipeService"]
