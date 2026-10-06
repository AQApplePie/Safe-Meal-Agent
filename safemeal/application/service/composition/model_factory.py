"""根据配置装配语言模型能力。"""

from safemeal.config.settings import settings
from safemeal.application.contracts.agent.prompts import PromptBundle
from safemeal.application.agent.model.prompts import DEFAULT_PROMPT_BUNDLE
from safemeal.infrastructure.llm.openai_language_model_gateway import (
    OpenAILanguageModelGateway,
)


def create_language_model_gateway(
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    prompts: PromptBundle = DEFAULT_PROMPT_BUNDLE,
    decision_temperature: float = 0.0,
    answer_temperature: float = 0.2,
) -> OpenAILanguageModelGateway:
    return OpenAILanguageModelGateway(
        model=model or settings.OPENAI_MODEL,
        api_key=api_key
        if api_key is not None
        else settings.OPENAI_API_KEY or settings.LLM_API_KEY or "",
        base_url=base_url or settings.OPENAI_API_BASE,
        prompts=prompts,
        decision_temperature=decision_temperature,
        answer_temperature=answer_temperature,
        request_timeout=settings.LLM_REQUEST_TIMEOUT,
        max_retries=settings.LLM_MAX_RETRIES,
        max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        structured_repair_retries=settings.LLM_STRUCTURED_REPAIR_RETRIES,
        context_token_budget=settings.AGENT_CONTEXT_TOKEN_BUDGET,
    )
