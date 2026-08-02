from __future__ import annotations

import os
from pathlib import Path

import pytest

from safemeal.config.settings import settings
from safemeal.infrastructure.retrieval.neo4j.client import Neo4jDatabase
from safemeal.infrastructure.retrieval.neo4j.dietary_safety import (
    DietarySafeRecipeQueryService,
)
from safemeal.infrastructure.retrieval.neo4j.importers.recipe_importer import (
    RecipeGraphImporter,
)
from safemeal.infrastructure.retrieval.neo4j.importers.recipe_json_parser import (
    load_recipe_records,
)


def test_live_dietary_projection_is_complete_and_classifies_known_dishes() -> None:
    if os.getenv("RUN_NEO4J_DIETARY_INTEGRATION") != "1":
        pytest.skip("set RUN_NEO4J_DIETARY_INTEGRATION=1 after dietary sync")

    records, _ = load_recipe_records(Path(settings.NEO4J_RECIPE_JSON_PATH))
    expected = len({record.name for record in records})
    database = Neo4jDatabase(
        settings.NEO4J_URI,
        settings.NEO4J_USER,
        settings.NEO4J_PASSWORD,
        database=settings.NEO4J_DATABASE,
    )
    try:
        report = RecipeGraphImporter(database).dietary_safety_report(
            expected_dishes=expected
        )
    finally:
        database.close()

    assert report["closure_passed"] is True
    assert report["complete_dishes"] == expected
    assert report["incomplete_dishes"] == 0

    unsafe = DietarySafeRecipeQueryService().execute(
        excluded_ingredients=["花生"],
        target_dish="宫保鸡丁",
        recommend_limit=2,
        excluded_limit=2,
    )
    safe = DietarySafeRecipeQueryService().execute(
        excluded_ingredients=["花生"],
        target_dish="清蒸鲈鱼",
        recommend_limit=2,
        excluded_limit=2,
    )
    assert unsafe.unknown_recipes == []
    assert unsafe.excluded_recipes[0].name == "宫保鸡丁"
    assert any(item.name == "清蒸鲈鱼" for item in safe.safe_recipes)
