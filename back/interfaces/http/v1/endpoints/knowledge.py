"""Milvus document knowledge and Neo4j graph inspection APIs."""

from typing import Annotated, List

from fastapi import APIRouter, Body, Depends, HTTPException
from loguru import logger
from starlette.concurrency import run_in_threadpool

from SafeMealAgent.back.application.errors import ApplicationError
from SafeMealAgent.back.interfaces.http.dependencies import (
    get_knowledge_service,
    get_neo4j_graph_service,
    get_recipe_knowledge_service,
)
from SafeMealAgent.back.interfaces.http.models.knowledge import (
    GraphResponse,
    RecipeModel,
    SearchRequest,
    SearchResponse,
)
from SafeMealAgent.back.shared.types import JsonObject

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _internal_error(detail: str = "Internal server error") -> HTTPException:
    return HTTPException(status_code=500, detail=detail)


@router.post("/recipes", status_code=201)
async def add_recipe(
    recipe: RecipeModel,
    service=Depends(get_recipe_knowledge_service),
) -> JsonObject:
    try:
        recipe_id, success = await service.ingest_recipe(
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
async def add_recipes_batch(
    recipes: Annotated[List[RecipeModel], Body(min_length=1, max_length=100)],
    service=Depends(get_recipe_knowledge_service),
) -> JsonObject:
    try:
        result = await service.ingest_recipes_batch(
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


@router.post("/search", response_model=SearchResponse)
async def search_knowledge(
    request: SearchRequest,
    service=Depends(get_knowledge_service),
) -> SearchResponse:
    try:
        results = await service.search(query=request.query, top_k=request.top_k)
        return SearchResponse(results=results, count=len(results))
    except Exception as exc:
        logger.exception("Knowledge search failed")
        raise _internal_error("Knowledge search failed") from exc


@router.delete("/recipes/{recipe_id}")
async def delete_recipe(
    recipe_id: str,
    service=Depends(get_recipe_knowledge_service),
) -> JsonObject:
    try:
        success = await service.delete_recipe(recipe_id)
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
async def get_stats(
    service=Depends(get_knowledge_service),
) -> JsonObject:
    try:
        stats = await service.get_stats()
        return {"status": "success", "data": stats}
    except Exception as exc:
        logger.exception("Knowledge stats failed")
        raise _internal_error("Knowledge stats failed") from exc


@router.delete("/clear")
async def clear_knowledge_base(
    confirm: bool = False,
    service=Depends(get_knowledge_service),
) -> JsonObject:
    if not confirm:
        raise HTTPException(
            status_code=400, detail="confirm=true is required to clear the store"
        )

    try:
        success = await service.clear()
        if not success:
            raise HTTPException(status_code=500, detail="Failed to clear the store")
        return {"status": "success", "message": "Knowledge base cleared"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Knowledge clear failed")
        raise _internal_error("Knowledge clear failed") from exc


@router.get("/graph", response_model=GraphResponse)
async def get_default_graph(
    refresh: bool = False,
    service=Depends(get_neo4j_graph_service),
) -> GraphResponse:
    try:
        graph_payload = await run_in_threadpool(
            service.get_default_graph, refresh=refresh
        )
        return GraphResponse(**graph_payload)
    except Exception as exc:
        logger.exception("Neo4j graph retrieval failed")
        raise _internal_error("Neo4j graph retrieval failed") from exc
