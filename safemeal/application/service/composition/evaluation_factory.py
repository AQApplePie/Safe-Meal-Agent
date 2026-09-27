"""Run the benchmark directly against the current modular-monolith Agent."""

from __future__ import annotations

import os

from safemeal.application.service.composition.model_factory import (
    create_language_model_gateway,
)
from safemeal.application.agent.graph import build_agent_graph
from safemeal.application.agent.utils.prompts import DEFAULT_PROMPT_BUNDLE, PromptBundle
from safemeal.application.agent.execution_service import (
    AgentExecutionService,
)
from safemeal.application.service.recipes import RecipeGenerationService
from safemeal.application.service.composition.application_container import (
    ApplicationContainer,
)
from safemeal.config.settings import settings
from safemeal.application.contracts.evaluation.models import (
    EvaluationProfile,
)
from safemeal.application.agent.tool_registry import build_tool_executor


from safemeal.application.service.composition.dietary_search_factory import (
    create_dietary_search,
)


def _api_key(env_name: str) -> str:
    configured = {
        "LLM_API_KEY": settings.LLM_API_KEY,
        "OPENAI_API_KEY": settings.OPENAI_API_KEY,
        "DASHSCOPE_API_KEY": settings.LLM_API_KEY,
    }
    return (os.getenv(env_name) or configured.get(env_name) or "").strip()


def _prompt_bundle(profile: EvaluationProfile) -> PromptBundle:
    prompts = profile.prompts
    return PromptBundle(
        version=prompts.version,
        planner=prompts.planner or DEFAULT_PROMPT_BUNDLE.planner,
        reflection=prompts.reflection or DEFAULT_PROMPT_BUNDLE.reflection,
        answer=prompts.answer or DEFAULT_PROMPT_BUNDLE.answer,
        recipe_generation=prompts.recipe_generation
        or DEFAULT_PROMPT_BUNDLE.recipe_generation,
    )


def _enabled_tools(profile: EvaluationProfile) -> list[str]:
    configured = profile.tools.enabled_tools
    if configured is not None:
        return configured
    enabled = [
        "search_recipes",
        "get_recipe",
        "recommend_recipes",
        "generate_recipe",
    ]
    if settings.ENABLE_MILVUS and settings.ENABLE_EMBEDDINGS:
        enabled.append("milvus_vector_search")
    if settings.ENABLE_NEO4J:
        enabled.append("dietary_safe_recipe_query")
    return enabled


def build_evaluation_agent(
    profile: EvaluationProfile,
    container: ApplicationContainer,
) -> AgentExecutionService:
    """Build an isolated Agent so profile changes cannot mutate production singletons."""

    model = profile.model
    model_gateway = create_language_model_gateway(
        model=model.model,
        api_key=_api_key(model.api_key_env),
        base_url=model.base_url,
        prompts=_prompt_bundle(profile),
        decision_temperature=model.decision_temperature,
        answer_temperature=model.answer_temperature,
    )
    enabled = _enabled_tools(profile)
    tool_executor = build_tool_executor(
        document_knowledge_provider=container.get_document_knowledge_service,
        recipe_catalog=container.get_recipe_catalog(),
        recipe_generation_service=RecipeGenerationService(model_gateway),
        enabled_tools=enabled,
        timeout_seconds=profile.tools.timeout_seconds,
        dietary_search=create_dietary_search()
        if "dietary_safe_recipe_query" in enabled
        else None,
    )
    graph = build_agent_graph(
        model_gateway=model_gateway,
        tool_executor=tool_executor,
        max_iterations=profile.tools.max_iterations,
        history_messages=settings.AGENT_HISTORY_MESSAGES,
        max_tool_calls=settings.AGENT_MAX_TOOL_CALLS,
        max_model_tokens=settings.AGENT_MAX_MODEL_TOKENS,
        max_model_cost=settings.AGENT_MAX_COST,
    )
    return AgentExecutionService(
        graph,
        timeout_seconds=settings.AGENT_TIMEOUT,
        model_name=model.model,
        max_concurrency=1,
    )
