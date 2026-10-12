"""根据配置装配语言模型能力。"""

from safemeal.config.settings import settings
from safemeal.agent.contracts.prompts import PromptBundle
from safemeal.agent.runtime.model.prompts import DEFAULT_PROMPT_BUNDLE
from safemeal.infrastructure.llm.openai_language_model_gateway import (
    OpenAILanguageModelGateway,
)


# 方法说明：create_language_model_gateway
# 作用：根据配置创建语言模型网关及供应商路由。
# 入参：
#   model（str | None）：当前调用使用的模型名称；默认值为 None。
#   api_key（str | None）：调用外部供应商所需的 API 凭据；默认值为 None。
#   base_url（str | None）：外部服务的基础地址；默认值为 None。
#   prompts（PromptBundle）：带版本的 Agent 提示词集合；默认值为 DEFAULT_PROMPT_BUNDLE。
#   decision_temperature（float）：结构化决策阶段的模型采样温度；默认值为 0.0。
#   answer_temperature（float）：最终回答阶段的模型采样温度；默认值为 0.2。
# 出参：OpenAILanguageModelGateway；兼容 OpenAI 协议的语言模型调用网关。
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
