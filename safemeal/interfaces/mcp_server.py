"""SafeMeal capabilities exposed as Model Context Protocol tools."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from safemeal.application.contracts.recipes.catalog import RecipeQuery
from safemeal.application.contracts.workflow.models import WorkflowRequest
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.service.composition.application_container import ApplicationContainer
from safemeal.interfaces.http.authentication import authenticate_credentials


class McpAuthenticationMiddleware(BaseHTTPMiddleware):
    """Apply the same API-key/OIDC policy to the mounted MCP transport."""

    async def dispatch(self, request: Request, call_next):
        try:
            authenticate_credentials(
                api_key=request.headers.get("X-API-Key"),
                subject=request.headers.get("X-SafeMeal-User-ID"),
                tenant_id=request.headers.get("X-SafeMeal-Tenant-ID"),
                authorization=request.headers.get("Authorization"),
            )
        except Exception as exc:
            status_code = int(getattr(exc, "status_code", 401))
            return JSONResponse(
                {"detail": "MCP authentication failed"}, status_code=status_code
            )
        return await call_next(request)


def create_mcp_server(container: ApplicationContainer) -> FastMCP:
    server = FastMCP(
        "SafeMealAgent",
        instructions="食品安全查询、食谱检索和确定性营养分析工具。",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    @server.tool(name="food_safety_query")
    async def food_safety_query(
        question: str,
        excluded_ingredients: list[str] | None = None,
    ) -> dict[str, Any]:
        """Query food-safety evidence and dietary-safe recipes."""

        result = await container.get_chat_workflow().run(
            WorkflowRequest(
                message=question,
                user_id="mcp_anonymous",
                session_id=f"mcp-{uuid4().hex}",
                use_user_memory=False,
                context=AgentContext(
                    dietary_constraints={
                        "active": bool(excluded_ingredients),
                        "excluded_ingredients": excluded_ingredients or [],
                    }
                ),
            )
        )
        return result.model_dump(mode="json")

    @server.tool(name="recipe_search")
    async def recipe_search(
        query: str | None = None,
        include_ingredients: list[str] | None = None,
        exclude_ingredients: list[str] | None = None,
        max_calories: float | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search SafeMeal's typed recipe catalogue."""

        result = container.get_recipe_catalog().search(
            RecipeQuery(
                name_contains=query,
                include_ingredients=tuple(include_ingredients or ()),
                exclude_ingredients=tuple(exclude_ingredients or ()),
                max_calories=Decimal(str(max_calories))
                if max_calories is not None
                else None,
                limit=limit,
            )
        )
        return result.model_dump(mode="json")

    @server.tool(name="nutrition_analysis")
    async def nutrition_analysis(recipe_id: int) -> dict[str, Any]:
        """Return typed calories and macronutrients for a recipe."""

        recipe = container.get_recipe_catalog().get(recipe_id)
        per_serving = {
            "calories": recipe.nutrition.calories / recipe.servings,
            "protein_g": recipe.nutrition.protein_g / recipe.servings,
            "carbs_g": recipe.nutrition.carbs_g / recipe.servings,
            "fat_g": recipe.nutrition.fat_g / recipe.servings,
        }
        return {
            "recipe_id": recipe.id,
            "name": recipe.name,
            "servings": recipe.servings,
            "total": recipe.nutrition.model_dump(mode="json"),
            "per_serving": {key: str(value) for key, value in per_serving.items()},
        }

    return server


def create_authenticated_mcp_app(container: ApplicationContainer):
    server = create_mcp_server(container)
    app = server.streamable_http_app()
    app.add_middleware(McpAuthenticationMiddleware)
    return app


__all__ = ["create_authenticated_mcp_app", "create_mcp_server"]
