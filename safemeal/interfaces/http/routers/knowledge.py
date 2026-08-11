"""Milvus document ingestion and search APIs."""

from typing import Annotated, List

from fastapi import APIRouter, Body, Depends, HTTPException
from loguru import logger

from safemeal.application.exceptions import ApplicationError
from safemeal.application.use_cases.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.application.use_cases.knowledge.recipe_indexing import (
    RecipeDocumentIndexer,
)
from safemeal.interfaces import (
    get_document_knowledge_service,
    get_recipe_document_indexer,
)
from safemeal.interfaces import (
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    RecipeDocumentRequest,
)
from safemeal.shared.types import JsonObject

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _internal_error(detail: str = "Internal server error") -> HTTPException:
    return HTTPException(status_code=500, detail=detail)


@router.post("/recipes", status_code=201)
async def ingest_recipe_document(
    recipe: RecipeDocumentRequest,
    recipe_indexer: RecipeDocumentIndexer = Depends(get_recipe_document_indexer),
) -> JsonObject:
    try:
        recipe_id, success = await recipe_indexer.ingest_recipe(
            recipe_id=recipe.id,
            recipe_data=recipe.model_dump(),
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to add recipe")
        return {"status": "success", "message": "Recipe added", "recipe_id": recipe_id}
    except HTTPException:
        raise
    except ApplicationError as exc:
        logger.warning("Recipe ingestion failed: {}", exc)
        raise _internal_error("Failed to add recipe") from exc
    except Exception as exc:
        logger.exception("Unexpected error adding recipe")
        raise _internal_error("Failed to add recipe") from exc


@router.post("/recipes/batch", status_code=201)
async def ingest_recipe_documents(
    recipes: Annotated[List[RecipeDocumentRequest], Body(min_length=1, max_length=100)],
    recipe_indexer: RecipeDocumentIndexer = Depends(get_recipe_document_indexer),
) -> JsonObject:
    try:
        result = await recipe_indexer.ingest_recipes_batch(
            [recipe.model_dump() for recipe in recipes]
        )
        return {
            "status": "success",
            "message": f"Inserted {result['success']} recipes",
            "statistics": result,
        }
    except ApplicationError as exc:
        logger.warning("Batch recipe ingestion failed: {}", exc)
        raise _internal_error("Failed to add recipes") from exc
    except Exception as exc:
        logger.exception("Unexpected error in batch recipe ingestion")
        raise _internal_error("Failed to add recipes") from exc


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    request: KnowledgeSearchRequest,
    document_knowledge: DocumentKnowledgeService = Depends(
        get_document_knowledge_service
    ),
) -> KnowledgeSearchResponse:
    try:
        results = await document_knowledge.search(
            query=request.query, top_k=request.top_k
        )
        return KnowledgeSearchResponse(results=results, count=len(results))
    except Exception as exc:
        logger.exception("Knowledge search failed")
        raise _internal_error("Knowledge search failed") from exc


@router.delete("/recipes/{recipe_id}")
async def delete_recipe_document(
    recipe_id: str,
    recipe_indexer: RecipeDocumentIndexer = Depends(get_recipe_document_indexer),
) -> JsonObject:
    try:
        success = await recipe_indexer.delete_recipe(recipe_id)
        if not success:
            raise HTTPException(
                status_code=404, detail="Recipe not found or deletion failed"
            )
        return {"status": "success", "message": f"Recipe {recipe_id} deleted"}
    except HTTPException:
        raise
    except ApplicationError as exc:
        logger.warning("Recipe deletion failed recipe_id={}: {}", recipe_id, exc)
        raise _internal_error("Failed to delete recipe") from exc
    except Exception as exc:
        logger.exception("Unexpected recipe deletion failure recipe_id={}", recipe_id)
        raise _internal_error("Failed to delete recipe") from exc


@router.get("/stats")
async def get_knowledge_stats(
    document_knowledge: DocumentKnowledgeService = Depends(
        get_document_knowledge_service
    ),
) -> JsonObject:
    try:
        stats = await document_knowledge.get_collection_stats()
        return {"status": "success", "data": stats}
    except Exception as exc:
        logger.exception("Knowledge stats failed")
        raise _internal_error("Knowledge stats failed") from exc


@router.delete("/clear")
async def clear_knowledge_base(
    confirm: bool = False,
    document_knowledge: DocumentKnowledgeService = Depends(
        get_document_knowledge_service
    ),
) -> JsonObject:
    if not confirm:
        raise HTTPException(
            status_code=400, detail="confirm=true is required to clear the store"
        )

    try:
        success = await document_knowledge.clear_collection()
        if not success:
            raise HTTPException(status_code=500, detail="Failed to clear the store")
        return {"status": "success", "message": "Knowledge base cleared"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Knowledge clear failed")
        raise _internal_error("Knowledge clear failed") from exc
__all__ = ["router"]