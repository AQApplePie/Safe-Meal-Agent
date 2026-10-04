"""Read-only adapter for the bundled recipe JSON catalog."""

from __future__ import annotations

import json
import re
from pathlib import Path

from safemeal.application.contracts.recipes.lookup import (
    MenuRecipeCandidate,
    RecipeCandidate,
    RecipeLookupResult,
)
from safemeal.application.contracts.workflow.request_frame import MenuCategory
from safemeal.application.service.recipes.classification import (
    classify_menu_categories,
)
from safemeal.application.service.dietary_safety.recipe_safety import (
    ingredient_matches_forbidden_term,
)


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]", "", value.casefold())


class LocalRecipeDocumentCatalog:
    name = "local_json"

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._documents: dict[str, dict] | None = None

    def _load(self) -> dict[str, dict]:
        if self._documents is None:
            with self._path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise ValueError("recipe catalog root must be an object")
            self._documents = payload
        return self._documents

    def lookup(self, recipe_name: str) -> RecipeLookupResult:
        query = recipe_name.strip()
        try:
            documents = self._load()
            normalized = _normalize(query)
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

    def search_candidates(
        self,
        *,
        category: MenuCategory,
        exclude_names: frozenset[str],
        limit: int,
        exclude_ingredients: tuple[str, ...] = (),
    ) -> tuple[MenuRecipeCandidate, ...]:
        """Enumerate lightweight bundled candidates for a missing menu quota."""

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
            # A hard exclusion cannot be proven against an ingredient-less row.
            # Fail closed before the row can enter the Agent's candidate pool.
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
