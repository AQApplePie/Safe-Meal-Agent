"""Recipe-specific knowledge ingestion use cases."""

from __future__ import annotations

from uuid import uuid4

from SafeMealAgent.back.application.domain.recipe_formatter import format_recipe_document
from SafeMealAgent.back.application.errors import KnowledgeOperationError
from SafeMealAgent.back.application.use_cases.knowledge.service import KnowledgeService
from SafeMealAgent.back.shared.types import JsonObject


class RecipeKnowledgeService:
    """Ingest recipe records into the generic vector knowledge service."""

    def __init__(self, knowledge_service: KnowledgeService) -> None:
        self._knowledge_service = knowledge_service

    def create_recipe_id(self) -> str:
        return f"recipe_{uuid4().hex[:8]}"

    async def ingest_recipe(
        self,
        *,
        recipe_id: str | None,
        recipe_data: JsonObject,
    ) -> tuple[str, bool]:
        resolved_id = recipe_id or self.create_recipe_id()
        document = format_recipe_document(recipe_data)
        metadata = {
            "recipe_id": resolved_id,
            "document_id": resolved_id,
            "name": recipe_data.get("name", ""),
            "category": recipe_data.get("category", ""),
            "difficulty": recipe_data.get("difficulty", ""),
        }
        try:
            success = await self._knowledge_service.add_document(
                doc_id=resolved_id,
                title=str(recipe_data.get("name", "")),
                content=document,
                metadata=metadata,
            )
            return resolved_id, success
        except Exception as exc:
            raise KnowledgeOperationError("Failed to ingest recipe") from exc

    async def ingest_recipes_batch(self, recipes: list[JsonObject]) -> dict[str, int]:
        success_count = 0
        error_count = 0
        for recipe in recipes:
            try:
                recipe_id = recipe.get("id") or recipe.get("recipe_id")
                _, success = await self.ingest_recipe(
                    recipe_id=str(recipe_id) if recipe_id else None,
                    recipe_data=recipe,
                )
            except KnowledgeOperationError:
                error_count += 1
                continue
            if not success:
                error_count += 1
                continue
            success_count += 1
        return {"success": success_count, "error": error_count, "total": len(recipes)}

    async def delete_recipe(self, recipe_id: str) -> bool:
        try:
            return await self._knowledge_service.delete_document(recipe_id)
        except Exception as exc:
            raise KnowledgeOperationError("Failed to delete recipe") from exc
