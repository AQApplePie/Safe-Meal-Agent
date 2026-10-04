"""Manual real-provider end-to-end check for the authenticated chat chain.

The script sends the three user-authored questions verbatim. Expected behaviour is
checked only after each Agent response; no expected answer is injected into model
prompts. It intentionally creates a fresh account so memory persistence is tested
without relying on pre-existing user state.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:8000/api/v1"
QUESTIONS = (
    "我爱吃鱼，水煮鱼的材料是什么",
    "我对花生过敏，有没有什么没有花生的菜",
    "请你给我推荐几道家常菜。",
)


def request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = 360.0,
) -> tuple[int, dict[str, Any] | list[Any]]:
    """Call one JSON endpoint and preserve error payloads for diagnosis."""

    body = json.dumps(payload, ensure_ascii=False).encode() if payload else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"{BASE_URL}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {"raw": raw}
        return exc.code, detail


def require(condition: bool, message: str) -> None:
    """Raise a readable assertion without changing application behaviour."""

    if not condition:
        raise AssertionError(message)


def main() -> int:
    """Register, log in, ask three turns and validate persisted understanding."""

    unique = int(time.time() * 1000)
    email = f"safemeal-e2e-{unique}@example.com"
    password = "SafeMeal-E2E-2026"

    register_status, register = request_json(
        "POST",
        "/auth/register",
        {"email": email, "password": password, "display_name": "E2E User"},
    )
    require(register_status == 201, f"registration failed: {register}")

    login_status, login = request_json(
        "POST", "/auth/login", {"email": email, "password": password}
    )
    require(login_status == 200, f"login failed: {login}")
    require(isinstance(login, dict), "login response must be an object")
    token = str(login["access_token"])

    responses: list[dict[str, Any]] = []
    session_id: str | None = None
    for index, question in enumerate(QUESTIONS, start=1):
        payload: dict[str, Any] = {
            "message": question,
            "request_id": f"e2e-{unique}-{index}",
        }
        if session_id:
            payload["session_id"] = session_id
        status, response = request_json("POST", "/chat/", payload, token)
        require(status == 200, f"question {index} failed: {response}")
        require(isinstance(response, dict), f"question {index} response is not object")
        session_id = str(response["session_id"])
        responses.append(response)

    memory_status, memories = request_json("GET", "/chat/memories", token=token)
    require(memory_status == 200, f"memory query failed: {memories}")
    require(isinstance(memories, list), "memory response must be a list")

    # Question 1 must return an actual material list, rather than a generic recipe
    # explanation or an unrelated dish substituted for the exact-name request.
    answer_one = str(responses[0].get("message") or "")
    material_lines = [line for line in answer_one.splitlines() if line.startswith("-")]
    require("水煮鱼" in answer_one, "question 1 did not answer the named recipe")
    require(
        len(material_lines) >= 3, "question 1 did not return a complete material list"
    )

    # Questions 2 and 3 are validated against the independent Workflow review,
    # not merely against natural-language claims made by the model.
    for index in (1, 2):
        metadata = responses[index].get("metadata") or {}
        safe_names = list(metadata.get("safe_recipe_names") or [])
        reviews = list(metadata.get("recipe_reviews") or [])
        require(safe_names, f"question {index + 1} returned no reviewed safe recipes")
        require(
            all("花生" not in str(name) for name in safe_names),
            f"question {index + 1} published a peanut recipe: {safe_names}",
        )
        require(
            all(
                review.get("decision") == "passed"
                for review in reviews
                if review.get("name") in safe_names
            ),
            f"question {index + 1} published a recipe that did not pass review",
        )

    active_memories = [item for item in memories if item.get("is_active", True)]
    memory_text = json.dumps(active_memories, ensure_ascii=False)
    require("鱼" in memory_text, "fish preference was not persisted")
    require("花生" in memory_text, "peanut allergy was not persisted")

    answer_three = str(responses[2].get("message") or "")
    require(
        "鱼" in answer_three, "question 3 did not use the persisted fish preference"
    )

    # Print a redacted report: tokens and credentials are never included.
    report = {
        "registration": "passed",
        "login": "passed",
        "session_id": session_id,
        "turns": [
            {
                "question": question,
                "answer": response.get("message"),
                "route": response.get("route"),
                "metadata": response.get("metadata"),
            }
            for question, response in zip(QUESTIONS, responses)
        ],
        "memories": active_memories,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"E2E_ASSERTION_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
