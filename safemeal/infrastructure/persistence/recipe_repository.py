"""SQLAlchemy implementation of the authoritative structured recipe read model."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Literal, NoReturn, cast

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    and_,
    exists,
    func,
    not_,
    select,
)
from pydantic import ValidationError
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from safemeal.application.contracts.recipes.catalog import (
    RecipeQuery,
    RecipeSearchResult,
    RecipeSortField,
)
from safemeal.application.contracts.recipes.models import (
    CookingStep,
    Ingredient,
    IngredientQuantity,
    NutritionInfo,
    Recipe,
    RecipeDifficulty,
    normalize_quantity,
)
from safemeal.application.exceptions import (
    DatabaseOperationError,
    DatabaseUnavailableError,
    StoredDataIntegrityError,
)
from safemeal.infrastructure.persistence.database import get_engine


metadata = MetaData()
cuisines = Table(
    "cuisines",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(255), nullable=False),
)
recipes = Table(
    "recipes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(255), nullable=False),
    Column("description", Text),
    Column("total_time", Integer),
    Column("servings", Integer),
    Column("difficulty", String(20)),
    Column("cuisine_id", Integer),
    Column("total_calories", Numeric(10, 2)),
    Column("total_protein", Numeric(10, 2)),
    Column("total_carbs", Numeric(10, 2)),
    Column("total_fat", Numeric(10, 2)),
)
ingredients = Table(
    "ingredients",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(255), nullable=False),
    Column("category", String(100)),
    Column("calories", Numeric(10, 2)),
    Column("protein", Numeric(10, 2)),
    Column("carbs", Numeric(10, 2)),
    Column("fat", Numeric(10, 2)),
)
recipe_ingredients = Table(
    "recipe_ingredients",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("recipe_id", Integer, nullable=False),
    Column("ingredient_id", Integer, nullable=False),
    Column("quantity", String(100), nullable=False),
    Column("unit", String(50)),
    Column("prep_method", String(100)),
    Column("is_main", Boolean),
    Column("ingredient_type", String(20)),
)
recipe_steps = Table(
    "recipe_steps",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("recipe_id", Integer, nullable=False),
    Column("step_number", Integer, nullable=False),
    Column("action", String(100), nullable=False),
    Column("instruction", Text, nullable=False),
    Column("duration", Integer),
    Column("temperature", String(50)),
    Column("tips", Text),
)


class SqlAlchemyRecipeRepository:
    """Load recipe aggregates with a bounded four-query search plan."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine or get_engine()

    def search(self, query: RecipeQuery) -> RecipeSearchResult:
        try:
            predicate = self._search_predicate(query)
            recipe_source = recipes.outerjoin(
                cuisines, cuisines.c.id == recipes.c.cuisine_id
            )
            count_statement = (
                select(func.count(recipes.c.id))
                .select_from(recipe_source)
                .where(predicate)
            )
            order_column = {
                RecipeSortField.NAME: recipes.c.name,
                RecipeSortField.TOTAL_TIME: recipes.c.total_time,
                RecipeSortField.CALORIES: recipes.c.total_calories,
            }[query.sort_by]
            order_expression = (
                order_column.desc()
                if query.sort_order == "desc"
                else order_column.asc()
            )
            statement = (
                select(recipes, cuisines.c.name.label("cuisine_name"))
                .select_from(recipe_source)
                .where(predicate)
                .order_by(order_expression, recipes.c.id.asc())
                .offset(query.offset)
                .limit(query.limit)
            )
            with self._engine.connect() as connection:
                total = int(connection.execute(count_statement).scalar_one())
                recipe_rows = list(connection.execute(statement).mappings())
                aggregates = self._map_aggregates(connection, recipe_rows)
            return RecipeSearchResult(
                items=aggregates,
                total=total,
                offset=query.offset,
                limit=query.limit,
            )
        except OperationalError as exc:
            self._raise_database_error(exc)
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc
        except (InvalidOperation, ValidationError, ValueError) as exc:
            raise StoredDataIntegrityError() from exc

    def get(self, recipe_id: int) -> Recipe | None:
        if recipe_id <= 0:
            return None
        try:
            statement = (
                select(recipes, cuisines.c.name.label("cuisine_name"))
                .select_from(
                    recipes.outerjoin(cuisines, cuisines.c.id == recipes.c.cuisine_id)
                )
                .where(recipes.c.id == recipe_id)
            )
            with self._engine.connect() as connection:
                row = connection.execute(statement).mappings().one_or_none()
                if row is None:
                    return None
                return self._map_aggregates(connection, [row])[0]
        except OperationalError as exc:
            self._raise_database_error(exc)
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc
        except (InvalidOperation, ValidationError, ValueError) as exc:
            raise StoredDataIntegrityError() from exc

    @staticmethod
    def _raise_database_error(exc: OperationalError) -> NoReturn:
        original_args = getattr(exc.orig, "args", ())
        error_code = original_args[0] if original_args else None
        if exc.connection_invalidated or error_code in {1205, 1213, 2003, 2006, 2013}:
            raise DatabaseUnavailableError() from exc
        raise DatabaseOperationError() from exc

    @staticmethod
    def _search_predicate(query: RecipeQuery):
        predicates = []
        if query.name_contains:
            predicates.append(recipes.c.name.contains(query.name_contains))
        if query.exclude_recipe_ids:
            predicates.append(recipes.c.id.not_in(query.exclude_recipe_ids))
        if query.exclude_recipe_names:
            predicates.append(recipes.c.name.not_in(query.exclude_recipe_names))
        if query.difficulties:
            predicates.append(
                recipes.c.difficulty.in_([item.value for item in query.difficulties])
            )
        if query.cuisine:
            predicates.append(cuisines.c.name == query.cuisine)
        if query.max_total_time_minutes is not None:
            predicates.append(recipes.c.total_time <= query.max_total_time_minutes)
        if query.max_calories is not None:
            predicates.append(recipes.c.total_calories <= query.max_calories)
        for term in query.include_ingredients:
            included = (
                select(recipe_ingredients.c.id)
                .select_from(
                    recipe_ingredients.join(
                        ingredients,
                        ingredients.c.id == recipe_ingredients.c.ingredient_id,
                    )
                )
                .where(
                    recipe_ingredients.c.recipe_id == recipes.c.id,
                    ingredients.c.name.contains(term),
                )
            )
            predicates.append(exists(included))
        for term in query.exclude_ingredients:
            excluded = (
                select(recipe_ingredients.c.id)
                .select_from(
                    recipe_ingredients.join(
                        ingredients,
                        ingredients.c.id == recipe_ingredients.c.ingredient_id,
                    )
                )
                .where(
                    recipe_ingredients.c.recipe_id == recipes.c.id,
                    ingredients.c.name.contains(term),
                )
            )
            predicates.append(not_(exists(excluded)))
        return and_(*predicates) if predicates else and_(True)

    @staticmethod
    def _map_aggregates(
        connection: Connection,
        recipe_rows: list[RowMapping],
    ) -> tuple[Recipe, ...]:
        recipe_ids = [int(row["id"]) for row in recipe_rows]
        if not recipe_ids:
            return ()
        ingredient_rows = connection.execute(
            select(
                recipe_ingredients,
                ingredients.c.name.label("ingredient_name"),
                ingredients.c.category.label("ingredient_category"),
                ingredients.c.calories.label("ingredient_calories"),
                ingredients.c.protein.label("ingredient_protein"),
                ingredients.c.carbs.label("ingredient_carbs"),
                ingredients.c.fat.label("ingredient_fat"),
            )
            .select_from(
                recipe_ingredients.join(
                    ingredients,
                    ingredients.c.id == recipe_ingredients.c.ingredient_id,
                )
            )
            .where(recipe_ingredients.c.recipe_id.in_(recipe_ids))
            .order_by(recipe_ingredients.c.recipe_id, recipe_ingredients.c.id)
        ).mappings()
        step_rows = connection.execute(
            select(recipe_steps)
            .where(recipe_steps.c.recipe_id.in_(recipe_ids))
            .order_by(recipe_steps.c.recipe_id, recipe_steps.c.step_number)
        ).mappings()
        ingredients_by_recipe: dict[int, list[IngredientQuantity]] = defaultdict(list)
        for row in ingredient_rows:
            ingredient = Ingredient(
                id=int(row["ingredient_id"]),
                name=str(row["ingredient_name"]),
                category=row["ingredient_category"],
                nutrition=NutritionInfo(
                    calories=Decimal(row["ingredient_calories"] or 0),
                    protein_g=Decimal(row["ingredient_protein"] or 0),
                    carbs_g=Decimal(row["ingredient_carbs"] or 0),
                    fat_g=Decimal(row["ingredient_fat"] or 0),
                    basis="per_100g",
                ),
            )
            ingredients_by_recipe[int(row["recipe_id"])].append(
                IngredientQuantity(
                    ingredient=ingredient,
                    quantity=Decimal(str(row["quantity"])),
                    unit=str(row["unit"]),
                    normalized=normalize_quantity(row["quantity"], str(row["unit"])),
                    preparation=row["prep_method"],
                    is_main=bool(row["is_main"]),
                    ingredient_type=cast(
                        Literal["main", "auxiliary", "seasoning"],
                        str(row["ingredient_type"]),
                    ),
                )
            )
        steps_by_recipe: dict[int, list[CookingStep]] = defaultdict(list)
        for row in step_rows:
            steps_by_recipe[int(row["recipe_id"])].append(
                CookingStep(
                    number=int(row["step_number"]),
                    action=str(row["action"]),
                    instruction=str(row["instruction"]),
                    duration_minutes=int(row["duration"] or 0),
                    temperature=row["temperature"],
                    tips=row["tips"],
                )
            )
        return tuple(
            Recipe(
                id=int(row["id"]),
                name=str(row["name"]),
                description=row["description"],
                total_time_minutes=int(row["total_time"] or 0),
                servings=int(row["servings"]),
                difficulty=RecipeDifficulty(str(row["difficulty"])),
                cuisine=row["cuisine_name"],
                ingredients=tuple(ingredients_by_recipe[int(row["id"])]),
                steps=tuple(steps_by_recipe[int(row["id"])]),
                nutrition=NutritionInfo(
                    calories=Decimal(row["total_calories"] or 0),
                    protein_g=Decimal(row["total_protein"] or 0),
                    carbs_g=Decimal(row["total_carbs"] or 0),
                    fat_g=Decimal(row["total_fat"] or 0),
                    basis="per_recipe",
                ),
            )
            for row in recipe_rows
        )


__all__ = ["SqlAlchemyRecipeRepository"]
