"""Owned authenticated approval smoke test; model/tool fixtures make no provider calls."""

import json
import os
import runpy
import tempfile
from pathlib import Path
from uuid import uuid4

import secrets

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    root = ROOT
    os.chdir(root)
    with tempfile.TemporaryDirectory(prefix="safemeal-approval-auth-") as directory:
        os.environ.update(
            APP_ENV="test",
            ENABLE_OIDC="false",
            AUTH_JWT_SECRET=secrets.token_urlsafe(48),
            DATABASE_URL=f"sqlite:///{directory}/app.sqlite",
            AGENT_CHECKPOINT_PATH=f"{directory}/check.sqlite",
            AGENT_CHECKPOINT_DATABASE_URL="",
            NEO4J_RECIPE_JSON_PATH=f"{directory}/empty.json",
            REQUEST_UNDERSTANDING_BACKEND="rules",
            ENABLE_LLM="false",
            ENABLE_EMBEDDINGS="false",
            ENABLE_MILVUS="false",
            ENABLE_NEO4J="false",
            ENABLE_EXTERNAL_RECIPE_SEARCH="false",
            REDIS_RATE_LIMIT_URL="",
            RECIPE_CACHE_URL="",
            RECIPE_RANKING_REDIS_URL="",
            BEHAVIOR_EVENT_REDIS_URL="",
            INGESTION_QUEUE_URL="",
            DEBUG="false",
            UPLOAD_DIR=directory,
            METRICS_ENABLED="false",
        )
        Path(directory, "empty.json").write_text("{}")
        from safemeal.main import create_application
        from safemeal.infrastructure.persistence.database import Base, get_engine
        from safemeal.agent.gateway.service import AgentExecutionService
        from safemeal.agent.runtime.orchestration.graph import build_agent_graph
        from safemeal.infrastructure.persistence.langgraph_checkpoint import (
            SqliteCheckpointSaver,
        )
        from safemeal.infrastructure.persistence.checkpoint_serializer import (
            ContractCheckpointSerializer,
        )
        from fastapi.testclient import TestClient
        from loguru import logger

        logger.remove()
        fixture = runpy.run_path(str(root / "tests/refactor/test_approval_flow.py"))
        tools = fixture["Tools"]()
        app = create_application()
        logger.remove()
        Base.metadata.create_all(get_engine())

        def rebuild():
            app.state.container._agent_execution_service = AgentExecutionService(
                build_agent_graph(
                    model_gateway=fixture["Model"](),
                    tool_executor=tools,
                    checkpointer=SqliteCheckpointSaver(
                        Path(directory, "owned-checkpoints.sqlite"),
                        serde=ContractCheckpointSerializer(),
                    ),
                    approval_tool_names=frozenset({"recommend_recipes"}),
                )
            )

        rebuild()
        report = {
            "transport": "real FastAPI TestClient, registration and JWT authentication",
            "storage": "owned temporary SQLite and persisted checkpoints",
            "model_and_tools": "deterministic test doubles; no provider calls",
            "cases": [],
        }
        with TestClient(app) as client:
            tokens = []
            for name in ["one", "two"]:
                registration = client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": f"{name}@approval.eval.example",
                        "password": "SafeMeal-Eval-2026",
                        "display_name": "Synthetic Approval",
                    },
                )
                assert registration.status_code == 201
                tokens.append(registration.json()["access_token"])
            headers = {"Authorization": "Bearer " + tokens[0]}
            other = {"Authorization": "Bearer " + tokens[1]}
            for approved in [True, False]:
                before = len(tools.calls)
                paused = client.post(
                    "/api/v1/chat/",
                    headers=headers,
                    json={"message": "推荐一道晚餐", "request_id": str(uuid4())},
                )
                assert paused.status_code == 200
                data = paused.json()
                assert (
                    data["metadata"]["approval_required"] and len(tools.calls) == before
                )
                payload = {
                    "session_id": data["session_id"],
                    "message_id": int(data["message_id"]),
                    "approval_id": data["metadata"]["approval_id"],
                    "approved": approved,
                }
                unauth = client.post("/api/v1/chat/resume", json=payload).status_code
                cross = client.post(
                    "/api/v1/chat/resume", headers=other, json=payload
                ).status_code
                stale = client.post(
                    "/api/v1/chat/resume",
                    headers=headers,
                    json={**payload, "approval_id": "obsolete"},
                ).status_code
                new_turn = client.post(
                    "/api/v1/chat/",
                    headers=headers,
                    json={
                        "session_id": data["session_id"],
                        "message": "并发新任务",
                        "request_id": str(uuid4()),
                    },
                ).status_code
                assert (unauth, cross, stale, new_turn) == (401, 404, 409, 409)
                rebuild()
                resumed = client.post(
                    "/api/v1/chat/resume", headers=headers, json=payload
                )
                assert (
                    resumed.status_code == 200 and resumed.json()["status"] != "error"
                )
                duplicate = client.post(
                    "/api/v1/chat/resume", headers=headers, json=payload
                ).status_code
                assert duplicate == 409 and len(tools.calls) == before + int(approved)
                history = client.get(
                    "/api/v1/chat/history/" + data["session_id"], headers=headers
                ).json()
                assert (
                    len(history) == 2
                    and history[-1]["content"] == resumed.json()["message"]
                )
                audit = history[-1]["message_metadata"]["approval_history"]
                assert len(audit) == 1 and audit[0]["approved"] is approved
                report["cases"].append(
                    {
                        "approved": approved,
                        "pause_http": 200,
                        "checkpoint_reconstructed": True,
                        "unauthenticated_http": unauth,
                        "cross_user_http": cross,
                        "stale_http": stale,
                        "new_turn_while_pending_http": new_turn,
                        "resume_http": 200,
                        "duplicate_http": duplicate,
                        "tool_calls_added": len(tools.calls) - before,
                        "persisted_same_message": history[-1]["id"]
                        == payload["message_id"],
                        "decision_audit_entries": len(audit),
                        "safety_review": resumed.json()["metadata"]["safety_review"],
                    }
                )
        report["passed"] = True
        Path(root, "evaluation_results/agent_approval_authenticated.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
