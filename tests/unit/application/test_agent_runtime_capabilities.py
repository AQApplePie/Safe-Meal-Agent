from __future__ import annotations

import asyncio

from SafeMealAgent.back.application.agents.graph import build_agent_graph
from SafeMealAgent.back.application.agents.models import (
    Observation,
    PlanDecision,
    ReflectionDecision,
    ToolCall,
)
from SafeMealAgent.back.application.agents.retrieval_fusion import fuse_retrieval_observations
from SafeMealAgent.back.application.agents.prompts import DEFAULT_PROMPT_BUNDLE, PromptBundle
from SafeMealAgent.back.application.use_cases.agent.graph_runner_service import AgentGraphRunnerService
from SafeMealAgent.back.application.use_cases.agent.conversation_memory import (
    ConversationMemoryManager,
    MemoryRelevanceSelector,
)
from SafeMealAgent.back.application.use_cases.agent.context_builder import (
    AgentContextBuilder,
    MemoryContextProvider,
)
from SafeMealAgent.back.shared.contracts.common import AnswerSource, RouterInfo
from SafeMealAgent.back.shared.contracts.tools import ToolResult, ToolSpecification


def _call(call_id: str, query: str = "宫保鸡丁") -> ToolCall:
    return ToolCall(
        id=call_id,
        tool_name="milvus_vector_search",
        arguments={"query": query},
        purpose="检索证据",
        success_criteria="返回相关文档",
    )


def _observation(
    tool_name: str,
    data: dict,
    *,
    ok: bool = True,
    has_data: bool = True,
) -> Observation:
    return Observation(
        call_id=f"{tool_name}-call",
        tool_name=tool_name,
        purpose="检索",
        success_criteria="返回证据",
        ok=ok,
        status="ok" if ok else "unavailable",
        has_data=has_data,
        summary="result",
        data=data,
        error=None if ok else "provider unavailable",
    )


def test_multi_route_fusion_deduplicates_and_weight_ranks_evidence() -> None:
    fused = fuse_retrieval_observations(
        [
            _observation(
                "milvus_vector_search",
                {
                    "documents": [
                        {
                            "document_id": "gongbao",
                            "content": "宫保鸡丁包含鸡肉和花生",
                        }
                    ]
                },
            ),
            _observation(
                "lightrag_search",
                {"response": "宫保鸡丁属于川菜"},
            ),
            _observation(
                "search_recipes",
                {
                    "items": [
                        {
                            "document_id": "gongbao",
                            "name": "宫保鸡丁",
                        }
                    ]
                },
            ),
        ]
    )

    assert fused is not None and fused.ok
    documents = fused.data["documents"]
    assert len(documents) == 2
    assert documents[0]["evidence_id"] == "document_id:gongbao"
    assert set(documents[0]["sources"]) == {
        "milvus_vector_search",
        "search_recipes",
    }


def test_multi_route_fusion_preserves_success_when_one_route_fails() -> None:
    fused = fuse_retrieval_observations(
        [
            _observation(
                "milvus_vector_search",
                {"documents": [{"document_id": "d1", "content": "有效证据"}]},
            ),
            _observation("lightrag_search", {}, ok=False, has_data=False),
        ]
    )

    assert fused is not None and fused.ok
    assert fused.data["count"] == 1
    assert fused.data["degraded_routes"] == ["lightrag_search"]


def test_prompt_bundle_is_versioned_and_stage_specific() -> None:
    bundle = DEFAULT_PROMPT_BUNDLE

    assert bundle.version == "default-v1"
    assert "Milvus 与 LightRAG" in bundle.planner
    assert "multi_route_retrieval" in bundle.reflection
    assert "degraded_routes" in bundle.answer
    assert len({bundle.planner, bundle.reflection, bundle.answer}) == 3

    custom = PromptBundle(
        version="interview-demo-v2",
        planner="custom planner",
        reflection=bundle.reflection,
        answer=bundle.answer,
        recipe_generation=bundle.recipe_generation,
    )
    assert custom.version == "interview-demo-v2"
    assert custom.planner == "custom planner"


def test_conversation_memory_compacts_history_within_token_budget() -> None:
    history = [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": f"第{index}轮对话：" + "宫保鸡丁和饮食要求" * 18,
        }
        for index in range(14)
    ]
    manager = ConversationMemoryManager(
        token_budget=320,
        response_token_reserve=80,
        minimum_recent_messages=2,
    )

    result = manager.prepare(history, current_message="继续刚才的话题")

    assert result.summarized_messages > 0
    assert result.episodic_memories[0]["memory_type"] == "conversation_episode"
    assert result.estimated_tokens <= 240
    assert result.history[-1]["content"] == history[-1]["content"]


def test_memory_relevance_keeps_hard_constraints_and_relevant_preferences() -> None:
    selector = MemoryRelevanceSelector(limit=2)
    selected = selector.select(
        "我最近想控糖，推荐晚餐",
        [
            {
                "memory_type": "cooking_equipment",
                "memory_key": "烤箱",
                "memory_value": "用户有烤箱",
                "confidence": 1,
            },
            {
                "memory_type": "health_goal",
                "memory_key": "控糖",
                "memory_value": "用户关注控糖",
                "confidence": 0.9,
            },
            {
                "memory_type": "dietary_allergy",
                "memory_key": "花生",
                "memory_value": "用户花生过敏",
                "confidence": 1,
            },
        ],
    )

    assert {item["memory_key"] for item in selected} == {"花生", "控糖"}


def test_context_builder_compacts_history_and_passes_message_identity_to_memory() -> (
    None
):
    class MemoryProvider:
        source_message_id: str | None = None

        def remember_from_message(self, **kwargs: object) -> list[dict]:
            self.source_message_id = str(kwargs.get("source_message_id"))
            return []

        def load_agent_memories(self, **kwargs: object) -> list[dict]:
            return [
                {
                    "memory_type": "dietary_allergy",
                    "memory_key": "花生",
                    "memory_value": "用户花生过敏",
                    "confidence": 1,
                },
                {
                    "memory_type": "health_goal",
                    "memory_key": "控糖",
                    "memory_value": "用户关注控糖",
                    "confidence": 0.9,
                },
            ]

    provider = MemoryProvider()
    builder = AgentContextBuilder(
        providers=[
            MemoryContextProvider(
                memory_provider=provider,  # type: ignore[arg-type]
                selector=MemoryRelevanceSelector(limit=1),
            )
        ],
        conversation_manager=ConversationMemoryManager(
            token_budget=220,
            response_token_reserve=60,
            minimum_recent_messages=2,
        ),
    )
    history = [
        {"role": "user", "content": f"第{index}轮" + "旧对话" * 40}
        for index in range(8)
    ]

    context = builder.build_chat_context(
        user_id="u1",
        message="推荐晚餐",
        session_id="s1",
        source_message_id="m1",
        conversation_history=history,
    )

    assert provider.source_message_id == "m1"
    assert context.context_metadata["summarized_history_messages"] > 0
    assert context.episodic_memories
    assert context.user_memories[0]["memory_key"] == "花生"


class _LoopEngine:
    def __init__(self) -> None:
        self.reflect_calls = 0

    async def plan(self, **kwargs: object) -> PlanDecision:
        return PlanDecision(decision="tools", rationale="search", calls=[_call("c1")])

    async def reflect(self, **kwargs: object) -> ReflectionDecision:
        self.reflect_calls += 1
        return ReflectionDecision(
            decision="continue",
            rationale="repeat",
            evidence_sufficient=False,
            next_calls=[_call("c2")],
        )

    async def answer(self, **kwargs: object) -> str:
        return "基于当前证据回答"


class _LoopRegistry:
    def __init__(self) -> None:
        self.invocations = 0

    def specifications(self) -> list[ToolSpecification]:
        return [
            ToolSpecification(
                name="milvus_vector_search",
                description="search",
                arguments_schema={"type": "object"},
            )
        ]

    async def invoke_many(self, calls: list[ToolCall]) -> list[ToolResult]:
        self.invocations += len(calls)
        return [
            ToolResult(
                call_id=call.id,
                tool_name=call.tool_name,
                ok=True,
                data={"documents": [{"document_id": "d1", "content": "证据"}]},
            )
            for call in calls
        ]


def test_agent_loop_stops_repeated_identical_tool_call() -> None:
    engine = _LoopEngine()
    registry = _LoopRegistry()
    graph = build_agent_graph(
        engine=engine,  # type: ignore[arg-type]
        registry=registry,
        max_iterations=4,
        max_tool_calls=12,
    )

    result = asyncio.run(
        graph.ainvoke({"messages": [{"role": "user", "content": "查询宫保鸡丁"}]})
    )

    assert registry.invocations == 1
    assert result["iteration"] == 1
    assert result["loop_stop_reason"] == "duplicate_tool_call"
    assert "已经执行过" in result["missing_information"][0]


def test_agent_loop_stops_when_tool_call_budget_is_exhausted() -> None:
    engine = _LoopEngine()
    registry = _LoopRegistry()
    graph = build_agent_graph(
        engine=engine,  # type: ignore[arg-type]
        registry=registry,
        max_iterations=4,
        max_tool_calls=1,
    )

    result = asyncio.run(
        graph.ainvoke({"messages": [{"role": "user", "content": "查询宫保鸡丁"}]})
    )

    assert registry.invocations == 1
    assert engine.reflect_calls == 0
    assert result["budget_exhausted"] is True
    assert result["loop_stop_reason"] == "tool_call_budget"
    assert "部分结果" in result["messages"][-1].content


def test_agent_graph_adds_multi_route_fusion_observation() -> None:
    class Engine:
        async def plan(self, **kwargs: object) -> PlanDecision:
            return PlanDecision(
                decision="tools",
                rationale="cross validate",
                calls=[
                    _call("milvus-call"),
                    ToolCall(
                        id="lightrag-call",
                        tool_name="lightrag_search",
                        arguments={"query": "宫保鸡丁"},
                        purpose="关系证据",
                        success_criteria="返回跨文档关系",
                    ),
                ],
            )

        async def reflect(self, **kwargs: object) -> ReflectionDecision:
            return ReflectionDecision(
                decision="finish",
                rationale="enough",
                evidence_sufficient=True,
            )

        async def answer(self, **kwargs: object) -> str:
            observations = kwargs["observations"]
            assert any(
                item.tool_name == "multi_route_retrieval" for item in observations
            )
            return "融合证据回答"

    class Registry:
        def specifications(self) -> list[ToolSpecification]:
            return [
                ToolSpecification(
                    name=name,
                    description="search",
                    arguments_schema={"type": "object"},
                )
                for name in ("milvus_vector_search", "lightrag_search")
            ]

        async def invoke_many(self, calls: list[ToolCall]) -> list[ToolResult]:
            return [
                ToolResult(
                    call_id=call.id,
                    tool_name=call.tool_name,
                    ok=True,
                    data=(
                        {"documents": [{"document_id": "d1", "content": "原文"}]}
                        if call.tool_name == "milvus_vector_search"
                        else {"response": "跨文档关系"}
                    ),
                )
                for call in calls
            ]

    result = asyncio.run(
        build_agent_graph(
            engine=Engine(),  # type: ignore[arg-type]
            registry=Registry(),  # type: ignore[arg-type]
        ).ainvoke({"messages": [{"role": "user", "content": "联合检索"}]})
    )

    fused = [
        item
        for item in result["observations"]
        if item.tool_name == "multi_route_retrieval"
    ]
    assert len(fused) == 1
    assert fused[0].data["count"] == 2


def test_pure_knowledge_question_overrides_recipe_lookup_with_milvus() -> None:
    class Engine:
        async def plan(self, **kwargs: object) -> PlanDecision:
            return PlanDecision(
                decision="tools",
                rationale="mistaken structured lookup",
                calls=[
                    ToolCall(
                        id="wrong-recipe-call",
                        tool_name="search_recipes",
                        arguments={"keyword": "宫保鸡丁"},
                        purpose="查菜谱",
                        success_criteria="返回菜谱",
                    )
                ],
            )

        async def reflect(self, **kwargs: object) -> ReflectionDecision:
            return ReflectionDecision(
                decision="finish", rationale="enough", evidence_sufficient=True
            )

        async def answer(self, **kwargs: object) -> str:
            return "鸡肉、花生，35分钟"

    class Registry:
        calls: list[ToolCall] = []

        def specifications(self) -> list[ToolSpecification]:
            return [
                ToolSpecification(
                    name=name,
                    description="search",
                    arguments_schema={"type": "object"},
                )
                for name in ("search_recipes", "milvus_vector_search")
            ]

        async def invoke_many(self, calls: list[ToolCall]) -> list[ToolResult]:
            self.calls.extend(calls)
            return [
                ToolResult(
                    call_id=call.id,
                    tool_name=call.tool_name,
                    ok=True,
                    data={
                        "documents": [
                            {
                                "document_id": "eval-doc-gongbao",
                                "content": "核心食材是鸡肉、花生，总用时35分钟",
                            }
                        ]
                    },
                )
                for call in calls
            ]

    registry = Registry()
    result = asyncio.run(
        build_agent_graph(
            engine=Engine(),  # type: ignore[arg-type]
            registry=registry,  # type: ignore[arg-type]
        ).ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "宫保鸡丁的核心食材和项目样例用时是什么？",
                    }
                ]
            }
        )
    )

    assert [call.tool_name for call in registry.calls] == ["milvus_vector_search"]
    assert registry.calls[0].arguments["query"].startswith("宫保鸡丁")
    assert result["evidence_sufficient"] is True


def test_targeted_dietary_query_does_not_add_recommendation_and_skips_reflection() -> None:
    class Engine:
        reflect_calls = 0

        async def plan(self, **kwargs: object) -> PlanDecision:
            return PlanDecision(
                decision="tools",
                rationale="target safety",
                calls=[
                    ToolCall(
                        id="target-safety",
                        tool_name="dietary_safe_recipe_query",
                        arguments={
                            "excluded_ingredients": ["鸡蛋"],
                            "target_dish": "番茄炒蛋",
                        },
                        purpose="判断目标菜是否安全",
                        success_criteria="返回目标菜分类",
                    )
                ],
            )

        async def reflect(self, **kwargs: object) -> ReflectionDecision:
            self.reflect_calls += 1
            raise AssertionError("targeted evidence should bypass model reflection")

        async def answer(self, **kwargs: object) -> str:
            raise AssertionError("dietary answer is rendered deterministically")

    class Registry:
        calls: list[ToolCall] = []

        def specifications(self) -> list[ToolSpecification]:
            return [
                ToolSpecification(
                    name=name,
                    description="tool",
                    arguments_schema={"type": "object"},
                )
                for name in ("dietary_safe_recipe_query", "recommend_recipes")
            ]

        async def invoke_many(self, calls: list[ToolCall]) -> list[ToolResult]:
            self.calls.extend(calls)
            return [
                ToolResult(
                    call_id=call.id,
                    tool_name=call.tool_name,
                    ok=True,
                    data={
                        "target_dish": "番茄炒蛋",
                        "safe_recipes": [],
                        "excluded_recipes": [
                            {
                                "name": "番茄炒蛋",
                                "ingredients": ["番茄", "鸡蛋"],
                                "matched_forbidden_ingredients": ["鸡蛋"],
                            }
                        ],
                        "unknown_recipes": [],
                    },
                )
                for call in calls
            ]

    engine = Engine()
    registry = Registry()
    result = asyncio.run(
        build_agent_graph(
            engine=engine,  # type: ignore[arg-type]
            registry=registry,  # type: ignore[arg-type]
        ).ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "鸡蛋过敏，番茄炒蛋到底能不能吃",
                    }
                ]
            }
        )
    )

    assert [call.tool_name for call in registry.calls] == [
        "dietary_safe_recipe_query"
    ]
    assert engine.reflect_calls == 0
    assert result["evidence_sufficient"] is True
    assert "番茄炒蛋" in result["messages"][-1].content
    assert "鸡蛋" in result["messages"][-1].content


def test_runner_keeps_successful_evidence_when_supplemental_tool_times_out() -> None:
    class Graph:
        async def ainvoke(self, input_state: object) -> dict:
            return {
                "messages": [{"role": "assistant", "content": "番茄炒蛋命中鸡蛋，不能吃。"}],
                "router": RouterInfo(type="agent-tool-loop", logic="deterministic"),
                "sources": [
                    AnswerSource(
                        source="neo4j:dietary-safety",
                        tool="dietary_safe_recipe_query",
                        call_id="dietary-call",
                    )
                ],
                "observations": [
                    Observation(
                        call_id="dietary-call",
                        tool_name="dietary_safe_recipe_query",
                        purpose="判断目标菜",
                        success_criteria="返回分类",
                        ok=True,
                        status="ok",
                        has_data=True,
                        summary="番茄炒蛋命中鸡蛋",
                        data={
                            "target_dish": "番茄炒蛋",
                            "excluded_recipes": [
                                {
                                    "name": "番茄炒蛋",
                                    "matched_forbidden_ingredients": ["鸡蛋"],
                                }
                            ],
                        },
                    ),
                    Observation(
                        call_id="recommend-call",
                        tool_name="recommend_recipes",
                        purpose="附加推荐",
                        success_criteria="返回推荐",
                        ok=False,
                        status="unavailable",
                        has_data=False,
                        summary="timeout",
                        data={},
                        error="timeout",
                        error_code="tool_timeout",
                    ),
                ],
                "iteration": 1,
                "tool_call_count": 2,
                "evidence_sufficient": True,
            }

    response = asyncio.run(
        AgentGraphRunnerService(
            agent_graph=Graph(),  # type: ignore[arg-type]
            timeout_seconds=5,
            model_name="test-model",
        ).process("鸡蛋过敏，番茄炒蛋能不能吃", "session-1")
    )

    assert response.status == "degraded"
    assert response.error_code == "partial_evidence_unavailable"
    assert response.message == "番茄炒蛋命中鸡蛋，不能吃。"
    assert response.sources[0].tool == "dietary_safe_recipe_query"
