"""Bounded, deterministic Neo4j dietary-safety queries."""

from __future__ import annotations

from typing import Literal, Optional

from neo4j import READ_ACCESS, Record, Session
from pydantic import BaseModel, Field

from safemeal.modules.dietary_safety.dietary_constraints import RecipeSafetyRecord
from safemeal.modules.dietary_safety.recipe_safety import (
    match_forbidden_ingredients,
    normalize_ingredient_name,
)
from safemeal.modules.dietary_safety.ingredient_terms import (
    DERIVED_SUFFIXES,
    INGREDIENT_ALIASES,
    PREPARATION_PREFIXES,
)
from safemeal.config.settings import settings
from safemeal.infrastructure.retrieval.neo4j.recipe_graph import create_driver
from safemeal.shared.types import to_json_object


class DietarySafeRecipeQueryResult(BaseModel):
    """忌口/过敏专用查询工具返回值。"""

    database: str = "neo4j"
    query_type: str = "dietary_safe_recipe_query"
    target_dish: Optional[str] = None
    excluded_ingredients: list[str] = Field(default_factory=list)
    expanded_excluded_ingredients: list[str] = Field(default_factory=list)
    safe_recipes: list[RecipeSafetyRecord] = Field(default_factory=list)
    excluded_recipes: list[RecipeSafetyRecord] = Field(default_factory=list)
    unknown_recipes: list[RecipeSafetyRecord] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


def expand_excluded_ingredients(ingredients: list[str]) -> list[str]:
    """Expand configured aliases while preserving deterministic order."""

    seen: set[str] = set()
    expanded: list[str] = []
    for item in ingredients:
        key = str(item).strip()
        if not key:
            continue
        for alias in INGREDIENT_ALIASES.get(key, [key]):
            value = str(alias).strip()
            if value and value not in seen:
                seen.add(value)
                expanded.append(value)
    return expanded


def _forbidden_normalized_names(excluded_terms: list[str]) -> list[str]:
    """Materialize the exact names accepted by the domain matcher.

    This lets Neo4j filter rows before returning them without replacing the
    domain classifier.  Aliases plus controlled preparation prefixes and
    derived suffixes mirror ``ingredient_matches_forbidden_term``.
    """

    values: set[str] = set()
    for term in excluded_terms:
        normalized = normalize_ingredient_name(term)
        if not normalized:
            continue
        values.add(normalized)
        values.update(
            normalize_ingredient_name(f"{prefix}{normalized}")
            for prefix in PREPARATION_PREFIXES
        )
        values.update(
            normalize_ingredient_name(f"{normalized}{suffix}")
            for suffix in DERIVED_SUFFIXES
        )
    return sorted(value for value in values if value)


class SafeRecipeGraphSearch:
    """Classify bounded recipe rows using complete structured ingredients."""

    def search(
        self,
        *,
        excluded_ingredients: list[str],
        target_dish: Optional[str],
        recommend_limit: int,
        excluded_limit: int,
    ) -> DietarySafeRecipeQueryResult:
        excluded_terms = expand_excluded_ingredients(excluded_ingredients)
        if not excluded_terms:
            raise ValueError("至少需要一个非空的忌口/过敏食材")
        target_dish = str(target_dish).strip() if target_dish else None
        forbidden_names = _forbidden_normalized_names(excluded_terms)
        driver = create_driver()
        try:
            with driver.session(
                database=settings.NEO4J_DATABASE,
                default_access_mode=READ_ACCESS,
            ) as session:
                target = (
                    self._query_target_dish(
                        session,
                        target_dish,
                        excluded_terms,
                    )
                    if target_dish
                    else None
                )
                safe_recipes = self._query_safe_recipes(
                    session,
                    excluded_terms,
                    forbidden_names,
                    recommend_limit,
                )
                excluded_recipes = self._query_excluded_recipes(
                    session,
                    excluded_terms,
                    forbidden_names,
                    excluded_limit,
                )
                unknown_recipes: list[RecipeSafetyRecord] = []

                if target_dish and target is None:
                    unknown_recipes.append(
                        RecipeSafetyRecord(
                            name=target_dish,
                            safety_status="unknown",
                            reason="Neo4j 中未找到该菜，无法确认完整食材。",
                        )
                    )
                elif target is not None and target.safety_status == "excluded":
                    excluded_recipes = self._prepend_unique(target, excluded_recipes)
                elif target is not None and target.safety_status == "safe":
                    safe_recipes = self._prepend_unique(target, safe_recipes)
                elif target is not None:
                    unknown_recipes.append(target)

                has_evidence = bool(safe_recipes or excluded_recipes or unknown_recipes)
                return DietarySafeRecipeQueryResult(
                    target_dish=target_dish,
                    excluded_ingredients=excluded_ingredients,
                    expanded_excluded_ingredients=excluded_terms,
                    safe_recipes=safe_recipes[:recommend_limit],
                    excluded_recipes=excluded_recipes[:excluded_limit],
                    unknown_recipes=unknown_recipes,
                    missing_information=(
                        []
                        if has_evidence
                        else [
                            "Neo4j 未返回具有完整食材清单的安全菜品，"
                            "也未找到命中禁忌食材的证据。"
                        ]
                    ),
                )
        finally:
            driver.close()

    @staticmethod
    def _prepend_unique(
        target: RecipeSafetyRecord,
        rows: list[RecipeSafetyRecord],
    ) -> list[RecipeSafetyRecord]:
        return [target] + [row for row in rows if row.name != target.name]

    def _query_target_dish(
        self,
        session: Session,
        target_dish: str,
        excluded_terms: list[str],
    ) -> Optional[RecipeSafetyRecord]:
        query = """
        MATCH (d:Dish)
        WHERE d.name = $target_dish OR d.name CONTAINS $target_dish
        WITH d, CASE WHEN d.name = $target_dish THEN 0 ELSE 1 END AS match_rank
        ORDER BY match_rank, size(d.name), d.name
        LIMIT 2
        OPTIONAL MATCH
          (d)-[rel:HAS_MAIN_INGREDIENT|HAS_AUX_INGREDIENT]->(i:Ingredient)
        RETURN d.name AS name,
               collect(DISTINCT i.name) AS ingredients,
               count(rel) AS relationship_count,
               coalesce(d.ingredient_count, -1) AS expected_ingredient_count,
               coalesce(d.ingredient_data_complete, false) AS ingredient_data_complete,
               match_rank
        ORDER BY match_rank, size(name), name
        """
        rows = list(session.run(query, {"target_dish": target_dish}))
        if not rows:
            return None

        first = rows[0]
        if int(first.get("match_rank", 1)) != 0 and len(rows) > 1:
            candidates = sorted(str(row["name"]) for row in rows)
            return RecipeSafetyRecord(
                name=target_dish,
                safety_status="unknown",
                reason="菜名为模糊匹配且存在多个候选，无法确定目标菜。",
                evidence=[
                    to_json_object(
                        {
                            "source": "neo4j",
                            "type": "ambiguous_target_dish",
                            "candidates": candidates,
                        }
                    )
                ],
            )
        return self._record_from_row(first, "target_dish", excluded_terms)

    def _query_safe_recipes(
        self,
        session: Session,
        excluded_terms: list[str],
        forbidden_names: list[str],
        limit: int,
    ) -> list[RecipeSafetyRecord]:
        if limit <= 0:
            return []
        query = """
        MATCH (d:Dish)
        WHERE coalesce(d.ingredient_data_complete, false) = true
          AND coalesce(d.ingredient_count, 0) > 0
        OPTIONAL MATCH
          (d)-[rel:HAS_MAIN_INGREDIENT|HAS_AUX_INGREDIENT]->(i:Ingredient)
        WITH d,
             collect(DISTINCT i.name) AS ingredients,
             collect(DISTINCT coalesce(i.normalized_name, toLower(trim(i.name))))
               AS normalized_ingredients,
             count(rel) AS relationship_count
        WHERE relationship_count >= d.ingredient_count
          AND none(value IN normalized_ingredients WHERE value IN $forbidden_names)
        RETURN d.name AS name,
               ingredients,
               relationship_count,
               d.ingredient_count AS expected_ingredient_count,
               d.ingredient_data_complete AS ingredient_data_complete
        ORDER BY name
        LIMIT $limit
        """
        rows = session.run(
            query,
            {"forbidden_names": forbidden_names, "limit": limit},
        )
        records = [
            self._record_from_row(row, "safe_recipe", excluded_terms) for row in rows
        ]
        return [record for record in records if record.safety_status == "safe"]

    def _query_excluded_recipes(
        self,
        session: Session,
        excluded_terms: list[str],
        forbidden_names: list[str],
        limit: int,
    ) -> list[RecipeSafetyRecord]:
        if limit <= 0 or not forbidden_names:
            return []
        query = """
        MATCH (d:Dish)-[:HAS_MAIN_INGREDIENT|HAS_AUX_INGREDIENT]->(bad:Ingredient)
        WHERE coalesce(bad.normalized_name, toLower(trim(bad.name)))
              IN $forbidden_names
        WITH DISTINCT d
        ORDER BY d.name
        LIMIT $limit
        OPTIONAL MATCH
          (d)-[rel:HAS_MAIN_INGREDIENT|HAS_AUX_INGREDIENT]->(i:Ingredient)
        RETURN d.name AS name,
               collect(DISTINCT i.name) AS ingredients,
               count(rel) AS relationship_count,
               coalesce(d.ingredient_count, -1) AS expected_ingredient_count,
               coalesce(d.ingredient_data_complete, false) AS ingredient_data_complete
        ORDER BY name
        """
        rows = session.run(
            query,
            {"forbidden_names": forbidden_names, "limit": limit},
        )
        records = [
            self._record_from_row(row, "excluded_recipe", excluded_terms)
            for row in rows
        ]
        return [record for record in records if record.safety_status == "excluded"]

    def _record_from_row(
        self,
        row: Record,
        evidence_type: str,
        excluded_terms: list[str],
    ) -> RecipeSafetyRecord:
        name = str(row["name"])
        ingredients = sorted(
            {str(item).strip() for item in (row.get("ingredients") or []) if item}
        )
        matched = match_forbidden_ingredients(ingredients, excluded_terms)
        expected_count = int(row.get("expected_ingredient_count", -1))
        relationship_count = int(row.get("relationship_count", 0))
        declared_complete = bool(row.get("ingredient_data_complete", False))
        is_complete = (
            declared_complete
            and expected_count > 0
            and relationship_count >= expected_count
            and bool(ingredients)
        )

        status: Literal["safe", "excluded", "unknown"]
        if matched:
            status = "excluded"
            reason = "命中忌口/过敏食材，不能推荐。"
        elif is_complete:
            status = "safe"
            reason = "完整结构化食材清单未命中忌口/过敏食材。"
        else:
            status = "unknown"
            reason = "食材清单缺少完整性标记或关系数量不足，不能确认安全。"

        return RecipeSafetyRecord(
            name=name,
            ingredients=ingredients,
            matched_forbidden_ingredients=list(matched),
            safety_status=status,
            reason=reason,
            evidence=[
                to_json_object(
                    {
                        "source": "neo4j",
                        "type": evidence_type,
                        "dish": name,
                        "ingredients": ingredients,
                        "matched_forbidden_ingredients": matched,
                        "expected_ingredient_count": expected_count,
                        "relationship_count": relationship_count,
                        "ingredient_data_complete": declared_complete,
                    }
                )
            ],
        )
