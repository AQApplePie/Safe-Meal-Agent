"""食谱查询、推荐与生成的统一业务服务。"""

from __future__ import annotations

from typing import Literal

from safemeal.modules.dietary.application.dietary_filter import DietaryRecipeFilter
from safemeal.modules.recipe.contracts.catalog import (
    RecipeQuery,
    RecipeSearchResult,
)
from safemeal.modules.recipe.contracts.models import Recipe
from safemeal.modules.recipe.contracts.lookup import RecipeCandidate
from safemeal.modules.recipe.contracts.lookup import MenuRecipeCandidate
from safemeal.modules.recipe.ports.recipe_provider import RecipeProvider
from safemeal.shared.exceptions import (
    BusinessConstraintError,
    FeatureUnavailableError,
    ResourceNotFoundError,
)
from safemeal.modules.recipe.ports.recipe_repository import RecipeRepository


from safemeal.modules.recipe.contracts.generation import RecipeGenerationRequest
from safemeal.modules.recipe.contracts.generated import GeneratedRecipe
from safemeal.modules.dietary.application.generated_safety import (
    generated_recipe_violations,
)
from safemeal.modules.dietary.application.recipe_safety import (
    ingredient_matches_forbidden_term,
)
from safemeal.shared.exceptions import ModelOutputValidationError
from safemeal.modules.recipe.ports.recipe_generator import RecipeGenerator
from safemeal.modules.recipe.application.classification import classify_recipe
from safemeal.modules.recipe.application.food_category import recipe_matches_category


# 类说明（业务或基础设施实现类）：RecipeService
# 作用：实现食谱查询推荐与生成业务服务，封装该组件的业务处理与依赖协作。
class RecipeService:
    # 字段说明：_MAX_RECOMMENDATION_CANDIDATES
    # 作用：最大RECOMMENDATION候选数，供该组件初始化及运行控制使用。
    # 初始值：1000。
    _MAX_RECOMMENDATION_CANDIDATES = 1000

    # 方法说明：__init__
    # 作用：初始化食谱查询推荐与生成业务服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   repository（RecipeRepository）：当前业务依赖的仓储实现。
    #   model_gateway（RecipeGenerator | None）：语言模型调用能力；默认值为 None。
    #   recipe_filter（DietaryRecipeFilter | None）：菜谱饮食硬约束过滤器；默认值为 None。
    #   lookup_providers（tuple[RecipeProvider, ...]）：可用于菜谱补充查询的来源集合；默认值为 ()。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        repository: RecipeRepository,
        model_gateway: RecipeGenerator | None = None,
        recipe_filter: DietaryRecipeFilter | None = None,
        lookup_providers: tuple[RecipeProvider, ...] = (),
    ) -> None:
        # 实例属性说明：_model_gateway
        # 作用：语言模型调用能力。
        self._model_gateway = model_gateway
        # 实例属性说明：_repository
        # 作用：当前业务依赖的仓储实现。
        self._repository = repository
        # 实例属性说明：_recipe_filter
        # 作用：菜谱饮食硬约束过滤器。
        self._recipe_filter = recipe_filter or DietaryRecipeFilter()
        # 实例属性说明：_lookup_providers
        # 作用：可用于菜谱补充查询的来源集合。
        self._lookup_providers = lookup_providers

    # 方法说明：_normalize_name
    # 作用：清理并归一化名称，统一名称比较与去重。
    # 入参：
    #   value（str）：当前待转换或校验的值。
    # 出参：str；文本字符串。
    @staticmethod
    def _normalize_name(value: str) -> str:
        return "".join(
            character for character in value.casefold() if character.isalnum()
        )

    # 方法说明：_canonical_candidate
    # 作用：把候选菜品归一化为菜单规划所需的统一结构。
    # 入参：
    #   recipe（Recipe）：当前菜谱或菜谱记录。
    # 出参：RecipeCandidate；推荐候选食谱。
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

    # 方法说明：_missing_fields
    # 作用：列出集合实际结构中缺失的必需字段。
    # 入参：
    #   candidate（RecipeCandidate）：当前待筛选候选。
    #   required_fields（tuple[Literal['ingredients', 'steps', 'time',
    # 'nutrition'], ...]）：必须存在的字段集合。
    # 出参：tuple[Literal['ingredients', 'steps', 'time', 'nutrition'], ...]；允许值为
    # ('ingredients', 'steps', 'time', 'nutrition')组成的元组。
    @staticmethod
    def _missing_fields(
        candidate: RecipeCandidate,
        required_fields: tuple[
            Literal["ingredients", "steps", "time", "nutrition"], ...
        ],
    ) -> tuple[Literal["ingredients", "steps", "time", "nutrition"], ...]:
        missing: list[Literal["ingredients", "steps", "time", "nutrition"]] = []
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

    # 方法说明：search
    # 作用：通过食谱查询推荐与生成业务服务按查询条件检索候选及其证据。
    # 入参：
    #   query（RecipeQuery）：食谱筛选与推荐查询。
    # 出参：RecipeSearchResult；食谱查询与推荐结果。
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

    # 方法说明：_menu_candidate
    # 作用：将完整菜谱转换为菜单规划使用的轻量候选。
    # 入参：
    #   recipe（Recipe）：当前菜谱或菜谱记录。
    # 出参：MenuRecipeCandidate；轻量菜单候选菜品。
    @staticmethod
    def _menu_candidate(recipe: Recipe) -> MenuRecipeCandidate:
        ingredients = tuple(item.ingredient.name for item in recipe.ingredients)
        main = tuple(
            item.ingredient.name for item in recipe.ingredients if item.is_main
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

    # 方法说明：_search_menu_candidates
    # 作用：按菜单分类及排除条件召回候选菜品。
    # 入参：
    #   query（RecipeQuery）：食谱筛选与推荐查询。
    # 出参：RecipeSearchResult；食谱查询与推荐结果。
    def _search_menu_candidates(self, query: RecipeQuery) -> RecipeSearchResult:

        selected: list[MenuRecipeCandidate] = []
        seen_names = set(query.exclude_recipe_names)
        scanned = 0
        page_size = 50
        while (
            len(selected) < query.limit
            and scanned < self._MAX_RECOMMENDATION_CANDIDATES
        ):
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

    # 方法说明：get
    # 作用：通过食谱查询推荐与生成业务服务读取指定标识对应的业务对象。
    # 入参：
    #   recipe_id（int）：目标食谱的整数标识。
    # 出参：Recipe；完整食谱业务模型。
    def get(self, recipe_id: int) -> Recipe:
        recipe = self._repository.get(recipe_id)
        if recipe is None:
            raise ResourceNotFoundError("Recipe not found")
        return recipe

    # 方法说明：recommend
    # 作用：按安全要求筛选并排序已有食谱，返回推荐候选。
    # 入参：
    #   query（RecipeQuery）：食谱筛选与推荐查询。
    # 出参：RecipeSearchResult；食谱查询与推荐结果。
    def recommend(self, query: RecipeQuery) -> RecipeSearchResult:
        page_size = 50
        requested_count = query.requested_count or query.limit
        # 召回规模属于检索策略，不由 Planner 或用户目标决定。带有后置品类
        # 过滤时扩大扫描范围；普通推荐保持有上限的三倍过采样。
        candidate_limit = (
            200
            if query.food_categories or query.exclude_food_categories
            else min(50, max(requested_count * 3, requested_count + 6))
        )
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
        allowed = list(
            self._recipe_filter.filter_recipes(
                candidate_items,
                excluded_ingredients=query.exclude_ingredients,
                dietary_types=query.dietary_types,
            )
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
            items=tuple(selected),
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

    # 方法说明：generate
    # 作用：根据生成请求创建结构化菜谱并校验输出。
    # 入参：
    #   request（RecipeGenerationRequest）：结构化食谱生成请求。
    # 出参：GeneratedRecipe；模型生成菜谱。
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
