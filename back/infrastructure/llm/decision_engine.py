import json
import os
from datetime import datetime, timezone
from time import perf_counter
from typing import TypeAlias, TypeVar

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, BaseMessageChunk
from loguru import logger
from pydantic import BaseModel, SecretStr
import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

from SafeMealAgent.back.application.agents.models import (
    Observation,
    PlanDecision,
    ReflectionDecision,
)
from SafeMealAgent.back.application.errors import (
    ExternalModelError,
    ModelOutputValidationError,
    PartialStreamInterruptedError,
)
from SafeMealAgent.back.application.domain.recipe_generation import (
    GeneratedRecipe,
    RecipeGenerationRequest,
)
from SafeMealAgent.back.application.agents.prompts import (
    DEFAULT_PROMPT_BUNDLE,
    PromptBundle,
)
from SafeMealAgent.back.application.observability import (
    answer_stream_active,
    emit_answer_chunk,
    record_model_call,
)
from SafeMealAgent.back.config.settings import settings
from SafeMealAgent.back.infrastructure.llm.provider_router import (
    LLMProvider,
    LLMProviderRouter,
    ProviderRouteExhausted,
)
from SafeMealAgent.back.infrastructure.operations.rate_limit import RedisTokenBucket
from SafeMealAgent.back.shared.contracts.common import ConversationMessage
from SafeMealAgent.back.shared.contracts.tools import ToolSpecification
from SafeMealAgent.back.shared.types import to_json_object, to_json_value

StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)
ChatPromptMessage: TypeAlias = tuple[str, str]


def _is_placeholder_secret(value: str) -> bool:
    normalized = value.strip().casefold()
    return not normalized or normalized.startswith(("replace-", "change-me", "your-"))


def is_retryable_model_error(exc: Exception) -> bool:
    """Retry only transient transport, timeout, rate-limit and provider 5xx failures."""

    return isinstance(
        exc,
        (
            TimeoutError,
            ConnectionError,
            httpx.TimeoutException,
            httpx.TransportError,
            APIConnectionError,
            APITimeoutError,
            RateLimitError,
            InternalServerError,
        ),
    )


def _json_payload(value: object, max_chars: int = 24000) -> str:
    text = json.dumps(to_json_value(value), ensure_ascii=False, default=str, indent=2)
    if len(text) <= max_chars:
        return text
    return json.dumps(
        {
            "truncated": True,
            "original_chars": len(text),
            "preview": text[:max_chars],
        },
        ensure_ascii=False,
    )


def _compact_schema(value: object) -> object:
    """Keep validation-relevant JSON Schema fields and drop prompt-heavy metadata."""

    payload = to_json_value(value)
    if isinstance(payload, list):
        return [_compact_schema(item) for item in payload]
    if not isinstance(payload, dict):
        return payload
    ignored = {"title", "description", "examples", "$schema"}
    return {
        str(key): _compact_schema(item)
        for key, item in payload.items()
        if str(key) not in ignored
    }


def _compact_prompt_value(value: object, *, depth: int = 0) -> object:
    """Bound nested tool evidence before serializing it into an LLM prompt."""

    payload = to_json_value(value)
    if depth >= 7:
        return str(payload)[:500]
    if isinstance(payload, str):
        return payload if len(payload) <= 1800 else payload[:1800] + "..."
    if isinstance(payload, list):
        limit = 8 if depth <= 2 else 12
        compacted = [
            _compact_prompt_value(item, depth=depth + 1) for item in payload[:limit]
        ]
        if len(payload) > limit:
            compacted.append({"truncated_items": len(payload) - limit})
        return compacted
    if isinstance(payload, dict):
        compacted: dict[str, object] = {}
        for key, item in list(payload.items())[:36]:
            compacted[str(key)] = _compact_prompt_value(item, depth=depth + 1)
        return compacted
    return payload


def _tool_spec_payload(tool_specs: list[ToolSpecification]) -> list[object]:
    return [
        {
            "name": item.name,
            "description": item.description[:500],
            "arguments_schema": _compact_schema(item.arguments_schema),
        }
        for item in tool_specs
    ]


def _observation_payload(observations: list[Observation]) -> list[object]:
    selected = list(observations)
    fused = next(
        (
            item
            for item in reversed(selected)
            if item.tool_name == "multi_route_retrieval" and item.ok and item.has_data
        ),
        None,
    )
    if fused is not None:
        retrieval_names = {
            "search_recipes",
            "get_recipe",
            "recommend_recipes",
            "milvus_vector_search",
            "neo4j_readonly_query",
            "dietary_safe_recipe_query",
            "lightrag_search",
        }
        selected = [
            item
            for item in selected
            if item is fused or item.tool_name not in retrieval_names
        ]
    return [
        _compact_prompt_value(item.model_dump())
        for item in selected[-10:]
    ]


class OpenAIDecisionEngine:
    """通过 OpenAI 兼容接口实现结构化规划、反思与回答。"""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        prompts: PromptBundle = DEFAULT_PROMPT_BUNDLE,
        decision_temperature: float = 0.0,
        answer_temperature: float = 0.2,
        request_timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        """保存一份不可变的模型运行配置。"""

        self.model_name = model or settings.OPENAI_MODEL
        self.api_key = api_key or settings.OPENAI_API_KEY or settings.LLM_API_KEY
        self.base_url = base_url or settings.OPENAI_API_BASE
        self.prompts = prompts
        self.decision_temperature = decision_temperature
        self.answer_temperature = answer_temperature
        self.request_timeout = (
            settings.LLM_REQUEST_TIMEOUT if request_timeout is None else request_timeout
        )
        self.max_retries = (
            settings.LLM_MAX_RETRIES if max_retries is None else max_retries
        )
        if self.request_timeout <= 0:
            raise ValueError("request_timeout must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self._models: dict[tuple[str, float], ChatOpenAI] = {}
        providers = [
            LLMProvider(
                name="primary",
                model=self.model_name,
                base_url=self.base_url,
                api_key=self.api_key or "",
            )
        ]
        try:
            fallback_items = json.loads(settings.LLM_FALLBACKS_JSON)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM_FALLBACKS_JSON 必须是合法 JSON") from exc
        if not isinstance(fallback_items, list):
            raise ValueError("LLM_FALLBACKS_JSON 必须是数组")
        for index, item in enumerate(fallback_items):
            if not isinstance(item, dict):
                raise ValueError("LLM_FALLBACKS_JSON 每一项必须是对象")
            api_key = str(item.get("api_key") or "").strip()
            api_key_env = str(item.get("api_key_env") or "").strip()
            if api_key_env:
                api_key = str(
                    os.getenv(api_key_env) or getattr(settings, api_key_env, None) or ""
                ).strip()
            provider_name = str(item.get("name") or f"fallback-{index + 1}")
            extra_body_value = item.get("extra_body")
            if extra_body_value is not None and not isinstance(extra_body_value, dict):
                raise ValueError("LLM_FALLBACKS_JSON extra_body 必须是对象")
            if _is_placeholder_secret(api_key):
                logger.warning(
                    "agent.provider.skipped provider={} reason=missing_or_placeholder_credential "
                    "api_key_env={}",
                    provider_name,
                    api_key_env or "inline",
                )
                continue
            providers.append(
                LLMProvider(
                    name=provider_name,
                    model=str(item.get("model") or self.model_name),
                    base_url=str(item.get("base_url") or self.base_url).rstrip("/"),
                    api_key=api_key,
                    extra_body=(
                        to_json_object(extra_body_value)
                        if extra_body_value is not None
                        else None
                    ),
                )
            )
        self.provider_router: LLMProviderRouter[object] = LLMProviderRouter(
            providers,
            failure_threshold=settings.LLM_CIRCUIT_FAILURE_THRESHOLD,
            recovery_timeout=settings.LLM_CIRCUIT_RECOVERY_SECONDS,
            distributed_limiter=(
                RedisTokenBucket(settings.REDIS_RATE_LIMIT_URL, prefix="safemeal:model")
                if settings.REDIS_RATE_LIMIT_URL
                else None
            ),
            rate_limit_per_minute=settings.MODEL_RATE_LIMIT_PER_MINUTE,
        )

    def _model(
        self,
        temperature: float = 0.0,
        provider: LLMProvider | None = None,
    ) -> ChatOpenAI:
        resolved = provider or self.provider_router.providers[0]
        if not resolved.api_key:
            raise RuntimeError("未配置 OPENAI_API_KEY/LLM_API_KEY，无法进行 Agent 决策")
        cache_key = (resolved.name, temperature)
        cached = self._models.get(cache_key)
        if cached is not None:
            return cached
        model = ChatOpenAI(
            api_key=SecretStr(resolved.api_key),
            base_url=resolved.base_url,
            model=resolved.model,
            temperature=temperature,
            timeout=self.request_timeout,
            max_retries=self.max_retries,
            max_completion_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            extra_body=resolved.extra_body,
        )
        self._models[cache_key] = model
        return model

    async def close(self) -> None:
        await self.provider_router.close()

    async def _invoke_structured(
        self,
        *,
        stage: str,
        schema: type[StructuredOutput],
        messages: list[ChatPromptMessage],
        temperature: float = 0.0,
    ) -> StructuredOutput:
        """调用结构化模型并保留原始 AIMessage，以便读取 Token usage。

        LangChain 默认的 ``with_structured_output`` 只返回解析后的 Pydantic 模型，
        原始响应中的 usage 会随之丢失。``include_raw=True`` 同时返回 ``raw`` 与
        ``parsed``，让运行时Trace能够记录输入/输出Token。
        """

        logger.info(
            "agent.model.start stage={} model={} temperature={} message_count={} "
            "schema={}",
            stage,
            self.model_name,
            temperature,
            len(messages),
            schema.__name__,
        )

        async def invoke(provider: LLMProvider) -> StructuredOutput:
            current_messages = list(messages)
            repair_retries = settings.LLM_STRUCTURED_REPAIR_RETRIES
            for attempt in range(repair_retries + 1):
                started_at = datetime.now(timezone.utc)
                started_perf = perf_counter()
                raw_response = None
                parsed_response = None
                call_stage = stage if attempt == 0 else f"{stage}_repair"
                structured_model = self._model(
                    temperature, provider
                ).with_structured_output(schema, include_raw=True)
                try:
                    envelope = await structured_model.ainvoke(current_messages)
                    raw_response = envelope.get("raw")
                    parsed_response = envelope.get("parsed")
                    parsing_error = envelope.get("parsing_error")
                    if parsing_error is not None or parsed_response is None:
                        raise ModelOutputValidationError() from parsing_error
                    record_model_call(
                        stage=call_stage,
                        model=provider.model,
                        temperature=temperature,
                        messages=current_messages,
                        response=raw_response,
                        parsed_response=parsed_response,
                        started_at=started_at,
                        started_perf=started_perf,
                    )
                    return parsed_response
                except ModelOutputValidationError as exc:
                    record_model_call(
                        stage=call_stage,
                        model=provider.model,
                        temperature=temperature,
                        messages=current_messages,
                        response=raw_response,
                        parsed_response=parsed_response,
                        started_at=started_at,
                        started_perf=started_perf,
                        error=str(exc),
                    )
                    if attempt >= repair_retries:
                        raise
                    raw_content = str(getattr(raw_response, "content", ""))[:4000]
                    current_messages = [
                        *messages,
                        *( [("assistant", raw_content)] if raw_content else [] ),
                        (
                            "human",
                            "上一条输出未通过结构化 Schema 校验。请保持原任务语义，"
                            "修复缺失字段、枚举值、空调用或重复调用 ID，并重新输出合法结构。\n"
                            f"目标 Schema：{_json_payload(_compact_schema(schema.model_json_schema()), 6000)}",
                        ),
                    ]
                except Exception as exc:
                    record_model_call(
                        stage=call_stage,
                        model=provider.model,
                        temperature=temperature,
                        messages=current_messages,
                        response=raw_response,
                        parsed_response=parsed_response,
                        started_at=started_at,
                        started_perf=started_perf,
                        error=str(exc),
                    )
                    raise
            raise ModelOutputValidationError()

        try:
            routed = await self.provider_router.execute(
                invoke,
                is_retryable=is_retryable_model_error,
            )
        except ModelOutputValidationError:
            raise
        except ProviderRouteExhausted as exc:
            raise ExternalModelError() from exc
        if not isinstance(routed, schema):
            raise RuntimeError(f"{stage} provider 返回类型错误")
        return routed

    async def plan(
        self,
        question: str,
        conversation_history: list[ConversationMessage],
        tool_specs: list[ToolSpecification],
        observations: list[Observation],
    ) -> PlanDecision:
        char_budget = settings.AGENT_CONTEXT_TOKEN_BUDGET * 4
        messages = [
            ("system", self.prompts.planner),
            (
                "human",
                "用户问题：\n"
                f"{question}\n\n对话历史：\n{_json_payload(conversation_history, max(2000, char_budget // 5))}\n\n"
                f"可用工具：\n{_json_payload(_tool_spec_payload(tool_specs), max(5000, char_budget // 2))}\n\n"
                f"既有 Observation：\n"
                f"{_json_payload(_observation_payload(observations), max(3000, char_budget * 3 // 10))}",
            ),
        ]
        return await self._invoke_structured(
            stage="planner",
            schema=PlanDecision,
            messages=messages,
            temperature=self.decision_temperature,
        )

    async def reflect(
        self,
        question: str,
        conversation_history: list[ConversationMessage],
        tool_specs: list[ToolSpecification],
        observations: list[Observation],
        iteration: int,
    ) -> ReflectionDecision:
        char_budget = settings.AGENT_CONTEXT_TOKEN_BUDGET * 4
        messages = [
            ("system", self.prompts.reflection),
            (
                "human",
                f"用户问题：\n{question}\n\n对话历史：\n"
                f"{_json_payload(conversation_history, max(2000, char_budget * 3 // 20))}\n\n当前迭代：{iteration}\n\n"
                f"可用工具：\n{_json_payload(_tool_spec_payload(tool_specs), max(5000, char_budget * 7 // 20))}\n\n"
                f"Observation：\n"
                f"{_json_payload(_observation_payload(observations), max(5000, char_budget // 2))}",
            ),
        ]
        return await self._invoke_structured(
            stage="reflection",
            schema=ReflectionDecision,
            messages=messages,
            temperature=self.decision_temperature,
        )

    async def generate_recipe(
        self, request: RecipeGenerationRequest
    ) -> GeneratedRecipe:
        """Generate a candidate recipe through the same provider lifecycle."""

        return await self._invoke_structured(
            stage="recipe_generation",
            schema=GeneratedRecipe,
            messages=[
                ("system", self.prompts.recipe_generation),
                (
                    "human",
                    "结构化生成请求：\n" + _json_payload(request.model_dump()),
                ),
            ],
            temperature=self.answer_temperature,
        )

    async def answer(
        self,
        question: str,
        conversation_history: list[ConversationMessage],
        observations: list[Observation],
        reflection_rationale: str,
        evidence_sufficient: bool,
        missing_information: list[str],
    ) -> str:
        char_budget = settings.AGENT_CONTEXT_TOKEN_BUDGET * 4
        messages = [
            ("system", self.prompts.answer),
            (
                "human",
                f"用户问题：\n{question}\n\n对话历史：\n"
                f"{_json_payload(conversation_history, max(2000, char_budget // 5))}\n\n"
                f"Reflection：\n- 理由：{reflection_rationale or '无'}\n"
                f"- 证据充分：{evidence_sufficient}\n"
                f"- 缺失信息：{_json_payload(missing_information)}\n\n"
                f"Observation：\n"
                f"{_json_payload(_observation_payload(observations), max(6000, char_budget * 7 // 10))}",
            ),
        ]
        logger.info(
            "agent.model.start stage=responder model={} temperature={} "
            "message_count={}",
            self.model_name,
            self.answer_temperature,
            len(messages),
        )

        async def invoke(provider: LLMProvider) -> str:
            started_at = datetime.now(timezone.utc)
            started_perf = perf_counter()
            response: BaseMessage | None = None
            emitted_answer_text = False
            try:
                model = self._model(
                    temperature=self.answer_temperature, provider=provider
                )
                if answer_stream_active():
                    answer_parts: list[str] = []
                    accumulated: BaseMessageChunk | None = None
                    async for chunk in model.astream(messages):
                        accumulated = (
                            chunk if accumulated is None else accumulated + chunk
                        )
                        text = (
                            chunk.content
                            if isinstance(chunk.content, str)
                            else str(chunk.content)
                        )
                        if text:
                            answer_parts.append(text)
                            await emit_answer_chunk(text)
                            emitted_answer_text = True
                    answer = "".join(answer_parts)
                    response = accumulated
                else:
                    response = await model.ainvoke(messages)
                    answer = str(response.content)
                record_model_call(
                    stage="responder",
                    model=provider.model,
                    temperature=self.answer_temperature,
                    messages=messages,
                    response=response,
                    parsed_response=answer,
                    started_at=started_at,
                    started_perf=started_perf,
                )
                return answer
            except Exception as exc:
                record_model_call(
                    stage="responder",
                    model=provider.model,
                    temperature=self.answer_temperature,
                    messages=messages,
                    response=response,
                    parsed_response=None,
                    started_at=started_at,
                    started_perf=started_perf,
                    error=str(exc),
                )
                if emitted_answer_text:
                    raise PartialStreamInterruptedError() from exc
                raise

        try:
            routed = await self.provider_router.execute(
                invoke,
                is_retryable=is_retryable_model_error,
            )
        except ProviderRouteExhausted as exc:
            raise ExternalModelError() from exc
        return str(routed)
