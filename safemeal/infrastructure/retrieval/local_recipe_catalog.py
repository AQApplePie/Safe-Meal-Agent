"""实现知识与菜谱检索基础设施适配。"""

from __future__ import annotations

import json
from typing import Literal
import re
from pathlib import Path

from safemeal.modules.recipe.contracts.lookup import (
    MenuRecipeCandidate,
    RecipeCandidate,
    RecipeLookupResult,
)
from safemeal.shared.contracts.request_frame import MenuCategory
from safemeal.modules.recipe.application.classification import (
    classify_menu_categories,
)
from safemeal.modules.dietary.application.recipe_safety import (
    ingredient_matches_forbidden_term,
)


# 方法说明：_normalize
# 作用：在local_recipe_catalog内部清理并统一输入格式。
# 入参：
#   value（str）：当前待转换或校验的值。
# 出参：str；文本字符串。
def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]", "", value.casefold())


# 类说明（业务或基础设施实现类）：LocalRecipeDocumentCatalog
# 作用：实现本地食谱文档目录，封装该组件的业务处理与依赖协作。
class LocalRecipeDocumentCatalog:
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 初始值：'local_json'。
    name = "local_json"

    # 方法说明：__init__
    # 作用：初始化本地食谱文档目录，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   path（str | Path）：本次读取或写入的路径。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, path: str | Path) -> None:
        # 实例属性说明：_path
        # 作用：本次读取或写入的路径。
        self._path = Path(path)
        # 实例属性说明：_documents
        # 作用：待处理的文档或文档片段集合。
        # 类型：dict[str, dict] | None。
        # 初始值：None。
        self._documents: dict[str, dict] | None = None

    # 方法说明：_load
    # 作用：从配置的本地目录载入食谱文档数据。
    # 入参：
    #   无显式入参。
    # 出参：dict[str, dict]；按名称组织的本地食谱数据映射。
    def _load(self) -> dict[str, dict]:
        if self._documents is None:
            with self._path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise ValueError("recipe catalog root must be an object")
            self._documents = payload
        return self._documents

    # 方法说明：lookup
    # 作用：从配置的菜谱来源查找目标菜品及其食材证据。
    # 入参：
    #   recipe_name（str）：目标菜谱名称。
    # 出参：RecipeLookupResult；外部或本地菜谱查找结果。
    def lookup(self, recipe_name: str) -> RecipeLookupResult:
        query = recipe_name.strip()
        try:
            documents = self._load()
            normalized = _normalize(query)
            match_type: Literal["exact", "normalized", "lexical", "none"]
            if query in documents:
                name, match_type = query, "exact"
            else:
                normalized_matches = [
                    name for name in documents if _normalize(name) == normalized
                ]
                lexical_matches = [
                    name for name in documents if normalized in _normalize(name)
                ]
                candidates = normalized_matches or lexical_matches
                if not candidates:
                    return RecipeLookupResult(
                        status="NOT_FOUND", query=query, provider=self.name
                    )
                candidates.sort(key=lambda value: (len(_normalize(value)), value))
                name = candidates[0]
                match_type = "normalized" if normalized_matches else "lexical"
            row = documents[name]
            ingredients = []
            for section in ("主食材", "辅料"):
                for item in row.get(section, []) or []:
                    if isinstance(item, list) and item:
                        ingredients.append(
                            {
                                "name": str(item[0]),
                                "amount": str(item[1]) if len(item) > 1 else "适量",
                                "section": section,
                            }
                        )
            evidence = RecipeCandidate(
                name=name,
                ingredients=tuple(ingredients),
                steps=str(row.get("做法") or ""),
                source_type="local_json",
                source_url=None,
                source_title=str(self._path),
                confidence=1.0 if match_type in {"exact", "normalized"} else 0.85,
                persistent=False,
                ingredients_complete=bool(ingredients),
            )
            return RecipeLookupResult(
                status="FOUND",
                query=query,
                provider=self.name,
                match_type=match_type,
                items=(evidence,),
            )
        except Exception as exc:
            return RecipeLookupResult(
                status="ERROR",
                query=query,
                provider=self.name,
                error=f"{type(exc).__name__}: {exc}",
            )

    # 方法说明：search_candidates
    # 作用：按菜单类别和排除条件查询轻量食谱候选。
    # 入参：
    #   category（MenuCategory）：目标食材或菜品分类。
    #   exclude_names（frozenset[str]）：必须排除的菜品或名称集合。
    #   limit（int）：本次查询或处理的最大条目数。
    #   exclude_ingredients（tuple[str, ...]）：必须排除的食材集合；默认值为 ()。
    # 出参：tuple[MenuRecipeCandidate, ...]；轻量菜单候选菜品组成的元组。
    def search_candidates(
        self,
        *,
        category: MenuCategory,
        exclude_names: frozenset[str],
        limit: int,
        exclude_ingredients: tuple[str, ...] = (),
    ) -> tuple[MenuRecipeCandidate, ...]:

        candidates: list[MenuRecipeCandidate] = []
        for name, row in self._load().items():
            if name in exclude_names or not isinstance(row, dict):
                continue
            ingredients = [
                str(item[0])
                for section in ("主食材", "辅料")
                for item in row.get(section, []) or []
                if isinstance(item, list) and item
            ]

            if exclude_ingredients and not ingredients:
                continue
            if any(
                ingredient_matches_forbidden_term(ingredient, forbidden)
                for ingredient in ingredients
                for forbidden in exclude_ingredients
            ):
                continue
            categories = classify_menu_categories(
                name=name,
                description=str(row.get("描述") or row.get("口味") or ""),
                ingredient_names=ingredients,
            )
            if category not in categories:
                continue
            candidates.append(
                MenuRecipeCandidate(
                    name=name,
                    categories=categories,
                    main_ingredients=tuple(ingredients[:5]),
                    ingredients=tuple(ingredients),
                    ingredients_complete=bool(ingredients),
                    source_type="local_json",
                    source_title=str(self._path),
                )
            )
            if len(candidates) >= limit:
                break
        return tuple(candidates)
