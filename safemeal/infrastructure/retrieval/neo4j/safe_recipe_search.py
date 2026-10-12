"""实现知识与菜谱检索基础设施适配。"""

from __future__ import annotations

from typing import Literal, Optional

from neo4j import READ_ACCESS, Record, Session

from safemeal.modules.dietary.contracts.constraints import RecipeSafetyRecord
from safemeal.modules.dietary.application.recipe_safety import (
    match_forbidden_ingredients,
    normalize_ingredient_name,
)
from safemeal.modules.dietary.application.ingredient_terms import (
    DERIVED_SUFFIXES,
    INGREDIENT_ALIASES,
    PREPARATION_PREFIXES,
)
from safemeal.shared.types import to_json_object
from safemeal.agent.runtime.tools.contracts.payloads import DietarySafeRecipeQueryResult


# 方法说明：expand_excluded_ingredients
# 作用：将禁止食材扩展为规范名、别名及类别成员。
# 入参：
#   ingredients（list[str]）：菜谱使用的完整食材集合。
# 出参：list[str]；归一化并扩展后的食材排除词项集合。
def expand_excluded_ingredients(ingredients: list[str]) -> list[str]:

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


# 方法说明：_forbidden_normalized_names
# 作用：将禁止食材归一化为用于安全匹配的名称集合。
# 入参：
#   excluded_terms（list[str]）：禁止词项及其规范化集合。
# 出参：list[str]；归一化并扩展后的食材排除词项集合。
def _forbidden_normalized_names(excluded_terms: list[str]) -> list[str]:

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


# 类说明（业务或基础设施实现类）：SafeRecipeGraphSearch
# 作用：实现Neo4j 安全食谱图查询器，封装该组件的业务处理与依赖协作。
class SafeRecipeGraphSearch:
    # 方法说明：__init__
    # 作用：初始化Neo4j 安全食谱图查询器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   driver_factory（由调用契约决定）：创建 Neo4j 驱动的工厂。
    #   database（str | None）：数据库名称或数据库配置；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, driver_factory, database: str | None = None):
        # 实例属性说明：_driver_factory
        # 作用：创建 Neo4j 驱动的工厂。
        self._driver_factory = driver_factory
        # 实例属性说明：_database
        # 作用：数据库名称或数据库配置。
        self._database = database

    # 方法说明：search
    # 作用：通过Neo4j 安全食谱图查询器按查询条件检索候选及其证据。
    # 入参：
    #   excluded_ingredients（list[str]）：必须排除的食材集合。
    #   target_dish（Optional[str]）：本轮要查询、替换或审核的目标菜品。
    #   recommend_limit（int）：最多推荐的菜品数。
    #   excluded_limit（int）：最多读取的排除记录数。
    # 出参：DietarySafeRecipeQueryResult；图安全食谱查询工具结果。
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
        driver = self._driver_factory()
        try:
            with driver.session(
                database=self._database,
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

    # 方法说明：_prepend_unique
    # 作用：将新条目前置并去重，保留近期内容的优先级。
    # 入参：
    #   target（RecipeSafetyRecord）：本轮要查询、替换或审核的目标菜品。
    #   rows（list[RecipeSafetyRecord]）：当前 SQL 查询结果行集合。
    # 出参：list[RecipeSafetyRecord]；候选菜谱忌口审核记录的集合。
    @staticmethod
    def _prepend_unique(
        target: RecipeSafetyRecord,
        rows: list[RecipeSafetyRecord],
    ) -> list[RecipeSafetyRecord]:
        return [target] + [row for row in rows if row.name != target.name]

    # 方法说明：_query_target_dish
    # 作用：在图中查询目标菜品及其食材证据。
    # 入参：
    #   session（Session）：当前 SQL 会话或聊天会话对象。
    #   target_dish（str）：本轮要查询、替换或审核的目标菜品。
    #   excluded_terms（list[str]）：禁止词项及其规范化集合。
    # 出参：Optional[RecipeSafetyRecord]；候选菜谱忌口审核记录或 None。
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

    # 方法说明：_query_safe_recipes
    # 作用：按允许的食材及菜谱条件查询安全候选。
    # 入参：
    #   session（Session）：当前 SQL 会话或聊天会话对象。
    #   excluded_terms（list[str]）：禁止词项及其规范化集合。
    #   forbidden_names（list[str]）：必须排除的菜品或名称集合。
    #   limit（int）：本次查询或处理的最大条目数。
    # 出参：list[RecipeSafetyRecord]；候选菜谱忌口审核记录的集合。
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

    # 方法说明：_query_excluded_recipes
    # 作用：查询包含禁止食材的菜谱标识，用于图检索排除。
    # 入参：
    #   session（Session）：当前 SQL 会话或聊天会话对象。
    #   excluded_terms（list[str]）：禁止词项及其规范化集合。
    #   forbidden_names（list[str]）：必须排除的菜品或名称集合。
    #   limit（int）：本次查询或处理的最大条目数。
    # 出参：list[RecipeSafetyRecord]；候选菜谱忌口审核记录的集合。
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

    # 方法说明：_record_from_row
    # 作用：将 SQL 结果行转换为应用层记录对象。
    # 入参：
    #   row（Record）：当前 SQL 查询结果行。
    #   evidence_type（str）：证据来源或证据类别。
    #   excluded_terms（list[str]）：禁止词项及其规范化集合。
    # 出参：RecipeSafetyRecord；候选菜谱忌口审核记录。
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
