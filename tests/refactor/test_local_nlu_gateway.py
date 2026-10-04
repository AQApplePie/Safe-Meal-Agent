"""Contract tests for the MLX request-understanding HTTP adapter."""

import json

import httpx
import pytest

from safemeal.infrastructure.nlu.local_request_understanding import (
    LocalModelRequestUnderstandingGateway,
)


def _catalog(tmp_path):
    path = tmp_path / "recipes.json"
    path.write_text(
        json.dumps(
            {"柠檬蒸三文鱼": {}, "清蒸鲈鱼": {}, "黑椒香煎三文鱼": {}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.asyncio
async def test_gateway_maps_corrected_recipe_detail_to_request_frame(tmp_path):
    captured = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        output = {
            "intent": "recipe_detail",
            "target": {
                "raw_mention": "大柠檬蒸三文鱼",
                "canonical_name": "柠檬蒸三文鱼",
                "recipe_id": 1,
                "resolution": "corrected_user_input",
            },
            "requested_fields": ["steps"],
            "constraints": [],
            "memory_updates": [],
            "recommendation_count": None,
            "confidence": 0.94,
            "clarification_required": False,
            "clarification_question": None,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(output)}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    gateway = LocalModelRequestUnderstandingGateway(
        "http://nlu.test",
        catalog_path=_catalog(tmp_path),
        model_name="test-model",
        client=client,
    )
    frame = await gateway.understand("大柠檬蒸三文鱼怎么做", [])
    await client.aclose()

    assert frame.primary_task == "recipe_detail"
    assert frame.target.recipe_name == "柠檬蒸三文鱼"
    assert frame.requested_fields == ("steps",)
    assert frame.exact_match_required is True
    assert frame.backend == "local_model:mlx"
    user_payload = json.loads(captured["messages"][1]["content"])
    assert user_payload["catalog_candidates"][0]["name"] == "柠檬蒸三文鱼"


@pytest.mark.asyncio
async def test_gateway_preserves_constraints_memory_and_clarification(tmp_path):
    outputs = iter(
        [
            {
                "intent": "recipe_recommendation",
                "target": {
                    "raw_mention": "鱼",
                    "canonical_name": None,
                    "recipe_id": None,
                    "resolution": "unresolved",
                },
                "requested_fields": [],
                "constraints": [
                    {"kind": "include_ingredient", "value": "鱼", "required": True},
                    {"kind": "allergy", "value": "花生", "required": True},
                ],
                "memory_updates": [{"kind": "allergy", "value": "花生"}],
                "recommendation_count": 3,
                "confidence": 0.96,
                "clarification_required": False,
                "clarification_question": None,
            },
            {
                "intent": "clarify",
                "target": {
                    "raw_mention": None,
                    "canonical_name": None,
                    "recipe_id": None,
                    "resolution": "unresolved",
                },
                "requested_fields": [],
                "constraints": [],
                "memory_updates": [],
                "recommendation_count": None,
                "confidence": 0.42,
                "clarification_required": True,
                "clarification_question": "你想了解清蒸鲈鱼还是柠檬蒸三文鱼？",
            },
        ]
    )

    async def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(next(outputs), ensure_ascii=False)}}
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    gateway = LocalModelRequestUnderstandingGateway(
        "http://nlu.test",
        catalog_path=_catalog(tmp_path),
        model_name="test-model",
        client=client,
    )
    recommendation = await gateway.understand("我花生过敏，推荐三道鱼菜", [])
    clarification = await gateway.understand("那个菜怎么做", [])
    await client.aclose()

    assert recommendation.target.ingredient is None
    assert [(item.kind, item.value) for item in recommendation.current_constraints] == [
        ("allergy", "花生"),
        ("food_category", "fish"),
    ]
    assert [(item.kind, item.value) for item in recommendation.memory_updates] == [
        ("allergy", "花生")
    ]
    assert recommendation.recommendation_count == 3
    assert recommendation.turn_preferences == ()
    assert clarification.primary_task == "clarify"
    assert "清蒸鲈鱼" in clarification.clarification_question


@pytest.mark.asyncio
async def test_gateway_always_sends_bounded_history_for_implicit_followups(tmp_path):
    payloads = []

    async def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payloads.append(json.loads(body["messages"][1]["content"]))
        output = {
            "intent": "recipe_recommendation",
            "target": {
                "raw_mention": None,
                "canonical_name": None,
                "recipe_id": None,
                "resolution": "unresolved",
            },
            "requested_fields": [],
            "constraints": [],
            "memory_updates": [],
            "recommendation_count": 3,
            "confidence": 0.92,
            "clarification_required": False,
            "clarification_question": None,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(output)}}]},
        )

    history = [
        {"role": "user", "content": "我爱吃鱼"},
        {"role": "assistant", "content": "推荐你试试清蒸鲈鱼"},
    ]
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    gateway = LocalModelRequestUnderstandingGateway(
        "http://nlu.test",
        catalog_path=_catalog(tmp_path),
        model_name="test-model",
        client=client,
    )

    await gateway.understand("推荐几道家常菜", history)
    await gateway.understand("刚才第一道怎么做", history)
    await client.aclose()

    assert payloads[0]["recent_turns"] == [history[1]]
    assert payloads[0]["recent_recipe_entities"][0]["name"] == "清蒸鲈鱼"
    assert payloads[1]["recent_turns"] == [history[1]]
    assert payloads[1]["recent_recipe_entities"][0]["name"] == "清蒸鲈鱼"


@pytest.mark.asyncio
async def test_gateway_repairs_recommendation_label_when_model_requests_exact_steps(
    tmp_path,
):
    async def respond(_: httpx.Request) -> httpx.Response:
        output = {
            "intent": "recipe_recommendation",
            "target": {
                "raw_mention": "水煮鱼片",
                "canonical_name": "清蒸鲈鱼",
                "recipe_id": 2,
                "resolution": "corrected_user_input",
            },
            "requested_fields": ["steps"],
            "constraints": [],
            "memory_updates": [],
            "recommendation_count": None,
            "confidence": 0.92,
            "clarification_required": False,
            "clarification_question": None,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(output)}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    gateway = LocalModelRequestUnderstandingGateway(
        "http://nlu.test",
        catalog_path=_catalog(tmp_path),
        model_name="test-model",
        client=client,
    )
    frame = await gateway.understand("推荐一道清蒸鲈鱼的做法", [])
    await client.aclose()

    assert frame.primary_task == "recipe_detail"
    assert frame.requested_fields == ("steps",)
    assert frame.exact_match_required is True


@pytest.mark.asyncio
async def test_gateway_overlays_explicit_menu_quotas_without_llm_arithmetic(tmp_path):
    async def respond(_: httpx.Request) -> httpx.Response:
        output = {
            "intent": "recipe_recommendation",
            "target": {
                "raw_mention": None,
                "canonical_name": None,
                "recipe_id": None,
                "resolution": "unresolved",
            },
            "requested_fields": [],
            "constraints": [],
            "memory_updates": [],
            "recommendation_count": None,
            "confidence": 0.95,
            "clarification_required": False,
            "clarification_question": None,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(output)}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    gateway = LocalModelRequestUnderstandingGateway(
        "http://nlu.test",
        catalog_path=_catalog(tmp_path),
        model_name="test-model",
        client=client,
    )
    frame = await gateway.understand(
        "农村宴席要三道凉菜、三道热菜、三道汤", []
    )
    await client.aclose()

    assert frame.primary_task == "menu_planning"
    assert frame.scenario == "农村宴席"
    assert frame.recommendation_count == 9
    assert frame.menu_planning is not None
    assert frame.menu_planning.total_required == 9
