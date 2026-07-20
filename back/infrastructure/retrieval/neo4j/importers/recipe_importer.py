"""从 JSON 数据初始化菜谱知识图谱。"""

from pathlib import Path
from typing import Iterable, List, Optional

from loguru import logger

from SafeMealAgent.back.application.domain.dietary_safety import normalise_ingredient_name
from SafeMealAgent.back.infrastructure.retrieval.neo4j.client import Neo4jDatabase
from .recipe_json_parser import (
    IngredientProfile,
    RecipeRecord,
    load_ingredient_profiles,
    load_recipe_records,
)
from SafeMealAgent.back.shared.types import JsonObject


DIETARY_SYNC_QUERY = """
UNWIND $batch AS dish
MERGE (d:Dish {name: dish.name})
SET d.ingredient_count = dish.ingredient_count,
    d.ingredient_data_complete = dish.ingredient_data_complete
FOREACH (item IN dish.main_ingredients |
    MERGE (i:Ingredient {name: item.name})
    SET i.normalized_name = item.normalized_name
    MERGE (d)-[rel:HAS_MAIN_INGREDIENT]->(i)
    SET rel.amount_text = item.amount, rel.role = 'main'
)
FOREACH (item IN dish.aux_ingredients |
    MERGE (i:Ingredient {name: item.name})
    SET i.normalized_name = item.normalized_name
    MERGE (d)-[rel:HAS_AUX_INGREDIENT]->(i)
    SET rel.amount_text = item.amount, rel.role = 'aux'
)
"""


class RecipeGraphImporter:
    """Load recipes and ingredient metadata from JSON files into Neo4j."""

    def __init__(self, database: Neo4jDatabase, batch_size: int = 200) -> None:
        self._database = database
        self._batch_size = max(50, batch_size)

    def bootstrap_from_json(
        self,
        recipe_json: Path,
        ingredient_json: Optional[Path] = None,
        *,
        force: bool = False,
    ) -> bool:
        """Populate the graph from JSON sources."""
        try:
            recipes, ingredients_used = load_recipe_records(recipe_json)
        except FileNotFoundError:
            logger.warning(f"Recipe JSON not found at {recipe_json}, skipping import.")
            return False
        except Exception as exc:
            logger.error(f"Failed to parse recipe JSON: {exc}")
            return False

        if not recipes:
            logger.info("No recipe records found; skipping Neo4j bootstrap.")
            return False

        if not force and not self._is_graph_empty():
            logger.info("Neo4j dataset already populated; skipping bootstrap.")
            return False

        if force:
            logger.info("Forcing recipe graph reload from JSON.")
            self._database.execute("MATCH (n) DETACH DELETE n")
        else:
            logger.info("Recipe graph is empty; importing dataset from JSON.")

        profiles = load_ingredient_profiles(ingredient_json, ingredients_used)

        self._create_constraints()
        self._create_recipe_nodes(recipes)
        self._create_relationships(recipes)
        if profiles:
            self._attach_ingredient_metadata(profiles)

        logger.info(
            "Imported %s recipes and %s unique ingredients into Neo4j.",
            len(recipes),
            len(ingredients_used),
        )
        return True

    def sync_dietary_safety_from_json(self, recipe_json: Path) -> JsonObject:
        """Idempotently repair the structured ingredient safety projection.

        Existing dishes are first marked incomplete, so only rows proven by the
        versioned source dataset can subsequently be returned as safe. The sync
        merges missing dishes, ingredients and role relationships without
        deleting unrelated graph knowledge.
        """

        recipes, _ = load_recipe_records(recipe_json)
        if not recipes:
            raise ValueError("recipe dataset contains no usable records")
        self._create_constraints()
        self._database.execute(
            "MATCH (d:Dish) SET d.ingredient_data_complete = false"
        )
        serialised: list[JsonObject] = []
        for record in recipes:
            main = self._serialise_dietary_ingredients(record.main_ingredients)
            auxiliary = self._serialise_dietary_ingredients(record.aux_ingredients)
            expected = len(
                {
                    (item["role"], item["normalized_name"])
                    for item in main + auxiliary
                }
            )
            serialised.append(
                {
                    "name": record.name,
                    "ingredient_count": expected,
                    "ingredient_data_complete": bool(
                        record.ingredient_data_complete and expected > 0
                    ),
                    "main_ingredients": main,
                    "aux_ingredients": auxiliary,
                }
            )
        for batch in self._chunked(serialised):
            self._database.execute(DIETARY_SYNC_QUERY, {"batch": batch})
        unique_dishes = len({record.name for record in recipes})
        report = dict(
            self.dietary_safety_report(expected_dishes=unique_dishes)
        )
        report["source_records"] = len(recipes)
        report["duplicate_source_names"] = len(recipes) - unique_dishes
        return report

    @staticmethod
    def _serialise_dietary_ingredients(items: list) -> list[JsonObject]:
        return [
            {
                "name": item.name,
                "normalized_name": normalise_ingredient_name(item.name),
                "amount": item.amount,
                "role": item.role,
            }
            for item in items
            if normalise_ingredient_name(item.name)
        ]

    def dietary_safety_report(self, *, expected_dishes: int) -> JsonObject:
        rows = self._database.fetch(
            """
            MATCH (d:Dish)
            OPTIONAL MATCH
              (d)-[rel:HAS_MAIN_INGREDIENT|HAS_AUX_INGREDIENT]->(i:Ingredient)
            WITH d, count(rel) AS relationship_count,
                 count(CASE WHEN i.normalized_name IS NOT NULL AND
                                 trim(i.normalized_name) <> '' THEN 1 END)
                   AS normalized_relationship_count
            RETURN count(d) AS total_dishes,
                   count(CASE WHEN d.ingredient_data_complete = true AND
                                   d.ingredient_count > 0 AND
                                   relationship_count >= d.ingredient_count AND
                                   normalized_relationship_count = relationship_count
                              THEN 1 END) AS complete_dishes,
                   count(CASE WHEN NOT (d.ingredient_data_complete = true AND
                                       d.ingredient_count > 0 AND
                                       relationship_count >= d.ingredient_count AND
                                       normalized_relationship_count = relationship_count)
                              THEN 1 END) AS incomplete_dishes
            """
        )
        report = rows[0] if rows else {}
        complete = int(report.get("complete_dishes", 0))
        return {
            "expected_dishes": expected_dishes,
            "total_dishes": int(report.get("total_dishes", 0)),
            "complete_dishes": complete,
            "incomplete_dishes": int(report.get("incomplete_dishes", 0)),
            "closure_passed": complete >= expected_dishes,
        }

    def _is_graph_empty(self) -> bool:
        query = "MATCH (n:Dish) RETURN COUNT(n) AS count"
        result = self._database.fetch(query)
        count = result[0]["count"] if result else 0
        return count == 0

    def _chunked(self, data: Iterable[JsonObject]) -> Iterable[List[JsonObject]]:
        batch: List[JsonObject] = []
        for record in data:
            batch.append(record)
            if len(batch) >= self._batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def _create_constraints(self) -> None:
        """Create stable identity constraints and the dietary lookup index."""

        statements = (
            "CREATE CONSTRAINT dish_name_unique IF NOT EXISTS "
            "FOR (d:Dish) REQUIRE d.name IS UNIQUE",
            "CREATE CONSTRAINT ingredient_name_unique IF NOT EXISTS "
            "FOR (i:Ingredient) REQUIRE i.name IS UNIQUE",
            "CREATE INDEX ingredient_normalized_name IF NOT EXISTS "
            "FOR (i:Ingredient) ON (i.normalized_name)",
        )
        for statement in statements:
            self._database.execute(statement)

    def _create_recipe_nodes(self, recipes: List[RecipeRecord]) -> None:
        query = """
        UNWIND $batch AS dish
        MERGE (d:Dish {name: dish.name})
        SET d.cook_time = dish.cook_time,
            d.instructions = dish.instructions,
            d.ingredient_count = dish.ingredient_count,
            d.ingredient_data_complete = dish.ingredient_data_complete
        WITH d, dish
        FOREACH (flavor IN dish.flavors |
            MERGE (f:Flavor {name: flavor})
            MERGE (d)-[:HAS_FLAVOR]->(f)
        )
        FOREACH (method IN dish.methods |
            MERGE (m:CookingMethod {name: method})
            MERGE (d)-[:USES_METHOD]->(m)
        )
        FOREACH (dtype IN dish.dish_types |
            MERGE (t:DishType {name: dtype})
            MERGE (d)-[:BELONGS_TO_TYPE]->(t)
        )
        """

        serialised = [
            {
                "name": record.name,
                "cook_time": record.cook_time,
                "instructions": record.instructions,
                "flavors": record.flavors,
                "methods": record.methods,
                "dish_types": record.dish_types,
                "ingredient_count": len(
                    {
                        (item.role, normalise_ingredient_name(item.name))
                        for item in record.main_ingredients + record.aux_ingredients
                    }
                ),
                "ingredient_data_complete": record.ingredient_data_complete,
            }
            for record in recipes
        ]

        for batch in self._chunked(serialised):
            self._database.execute(query, {"batch": batch})

    def _create_relationships(self, recipes: List[RecipeRecord]) -> None:
        step_query = """
        UNWIND $batch AS dish
        MATCH (d:Dish {name: dish.name})
        FOREACH (step IN dish.steps |
            MERGE (s:CookingStep {dish_name: dish.name, order: step.order})
            SET s.order = step.order,
                s.instruction = step.instruction
            MERGE (d)-[hs:HAS_STEP]->(s)
            SET hs.order = step.order
        )
        """

        ingredient_query = """
        UNWIND $batch AS dish
        MATCH (d:Dish {name: dish.name})
        FOREACH (item IN dish.main_ingredients |
            MERGE (i:Ingredient {name: item.name})
            SET i.normalized_name = item.normalized_name
            MERGE (d)-[rel:HAS_MAIN_INGREDIENT]->(i)
            SET rel.amount_text = item.amount,
                rel.role = item.role
        )
        FOREACH (item IN dish.aux_ingredients |
            MERGE (i:Ingredient {name: item.name})
            SET i.normalized_name = item.normalized_name
            MERGE (d)-[rel:HAS_AUX_INGREDIENT]->(i)
            SET rel.amount_text = item.amount,
                rel.role = item.role
        )
        """

        steps_data = [
            {
                "name": record.name,
                "steps": [
                    {"order": step.order, "instruction": step.instruction}
                    for step in record.steps
                ],
            }
            for record in recipes
        ]
        ingredients_data = [
            {
                "name": record.name,
                "main_ingredients": [
                    {
                        "name": item.name,
                        "normalized_name": normalise_ingredient_name(item.name),
                        "amount": item.amount,
                        "role": item.role,
                    }
                    for item in record.main_ingredients
                ],
                "aux_ingredients": [
                    {
                        "name": item.name,
                        "normalized_name": normalise_ingredient_name(item.name),
                        "amount": item.amount,
                        "role": item.role,
                    }
                    for item in record.aux_ingredients
                ],
            }
            for record in recipes
        ]

        for batch in self._chunked(steps_data):
            self._database.execute(step_query, {"batch": batch})

        for batch in self._chunked(ingredients_data):
            self._database.execute(ingredient_query, {"batch": batch})

    def _attach_ingredient_metadata(self, profiles: List[IngredientProfile]) -> None:
        query = """
        UNWIND $profiles AS profile
        MERGE (i:Ingredient {name: profile.name})
        SET i.normalized_name = profile.normalized_name
        FOREACH (_ IN CASE WHEN profile.nutrition IS NULL THEN [] ELSE [1] END |
            MERGE (np:NutritionProfile {name: profile.name})
            SET np.description = profile.nutrition
            MERGE (i)-[:HAS_NUTRITION_PROFILE]->(np)
        )
        FOREACH (benefit IN profile.benefits |
            MERGE (hb:HealthBenefit {name: benefit})
            MERGE (i)-[:HAS_HEALTH_BENEFIT]->(hb)
        )
        """

        serialised = [
            {
                "name": profile.name,
                "normalized_name": normalise_ingredient_name(profile.name),
                "nutrition": profile.nutrition,
                "benefits": profile.benefits,
            }
            for profile in profiles
        ]

        for batch in self._chunked(serialised):
            self._database.execute(query, {"profiles": batch})
