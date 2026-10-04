"""Real authenticated E2E check for the composite banquet-planning path."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:8000/api/v1"
QUERY = (
    "我现在在进行农村宴席，请你帮我推荐十几道菜，"
    "要求三道凉菜，三道热菜，三道素菜，三道荤菜，三道汤，三道主食。"
)
EXPECTED = {
    "cold_dish": 3,
    "hot_dish": 3,
    "vegetarian": 3,
    "meat": 3,
    "soup": 3,
    "staple": 3,
}


def request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    token: str | None = None,
    *,
    timeout: float = 360.0,
) -> tuple[int, dict[str, Any]]:
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
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    unique = int(time.time() * 1000)
    email = f"safemeal-menu-{unique}@example.com"
    password = "SafeMeal-Menu-2026"
    register_status, register = request_json(
        "POST",
        "/auth/register",
        {"email": email, "password": password, "display_name": "Menu E2E"},
    )
    require(register_status == 201, f"registration failed: {register}")
    login_status, login = request_json(
        "POST", "/auth/login", {"email": email, "password": password}
    )
    require(login_status == 200, f"login failed: {login}")
    status, response = request_json(
        "POST",
        "/chat/",
        {"message": QUERY, "request_id": f"menu-{unique}"},
        str(login["access_token"]),
    )
    require(status == 200, f"menu request failed: {response}")

    metadata = response.get("metadata") or {}
    plan = metadata.get("menu_execution_plan") or {}
    progress = metadata.get("menu_task_progress") or {}
    selected = progress.get("selected_recipes") or []
    names = [str(item.get("name")) for item in selected]
    require(plan.get("scenario") == "农村宴席", f"unexpected scenario: {plan}")
    require(plan.get("required") == EXPECTED, f"unexpected quotas: {plan}")
    require(plan.get("distinct_recipes") is True, "distinct recipes was disabled")
    require(
        plan.get("allow_cross_category_counting") is False,
        "cross-category counting was unexpectedly enabled",
    )
    require(progress.get("fulfilled") == EXPECTED, f"incomplete menu: {progress}")
    require(len(names) == 18, f"expected 18 selected recipes, got {len(names)}")
    require(len(set(names)) == 18, f"duplicate recipes selected: {names}")
    require(metadata.get("safety_review") == "passed", f"safety failed: {metadata}")
    require(
        set(metadata.get("safe_recipe_names") or []) == set(names),
        "final safety did not approve the exact selected set",
    )

    def chat(message: str, suffix: str) -> dict[str, Any]:
        chat_status, chat_response = request_json(
            "POST",
            "/chat/",
            {"message": message, "request_id": f"menu-{unique}-{suffix}"},
            str(login["access_token"]),
        )
        require(chat_status == 200, f"regression {suffix} failed: {chat_response}")
        return chat_response

    ordinary = chat("我想吃鱼，不爱吃辣，推荐一道菜。", "ordinary")
    ordinary_metadata = ordinary.get("metadata") or {}
    require(
        not (ordinary_metadata.get("menu_execution_plan") or {}).get("required"),
        "ordinary recommendation incorrectly created a composite menu plan",
    )
    require(
        bool(ordinary_metadata.get("safe_recipe_names") or []),
        f"ordinary recommendation returned no reviewed recipe: {ordinary}",
    )

    simple_count = chat("推荐三道鱼。", "three-fish")
    simple_metadata = simple_count.get("metadata") or {}
    require(
        not (simple_metadata.get("menu_execution_plan") or {}).get("required"),
        "simple count incorrectly created a composite menu plan",
    )
    require(
        sum(
            line.startswith("- 「")
            for line in str(simple_count.get("message") or "").splitlines()
        )
        == 3,
        f"simple count did not return three reviewed recipes: {simple_count}",
    )

    smaller = chat("给我两道凉菜、两道热菜和一道汤。", "small-menu")
    smaller_metadata = smaller.get("metadata") or {}
    smaller_progress = smaller_metadata.get("menu_task_progress") or {}
    require(
        smaller_progress.get("fulfilled")
        == {"cold_dish": 2, "hot_dish": 2, "soup": 1},
        f"small composite menu was not completed: {smaller_progress}",
    )
    require(
        len(smaller_progress.get("selected_recipes") or []) == 5,
        "small composite menu did not contain five distinct recipes",
    )

    chat("请记住，我对花生过敏。", "remember-allergy")
    allergy_menu = chat(
        "请给我两道凉菜、两道热菜和一道汤。", "allergy-menu"
    )
    allergy_metadata = allergy_menu.get("metadata") or {}
    allergy_progress = allergy_metadata.get("menu_task_progress") or {}
    allergy_names = {
        str(item.get("name"))
        for item in allergy_progress.get("selected_recipes") or []
    }
    require(allergy_names, "allergy-aware composite menu selected no recipes")
    require(
        allergy_names == set(allergy_metadata.get("safe_recipe_names") or []),
        "a selected allergy-menu recipe did not pass final safety",
    )
    require(
        all(
            review.get("allergy_status") == "safe"
            for review in allergy_metadata.get("recipe_reviews") or []
            if review.get("name") in allergy_names
        ),
        "allergy-aware composite menu contains a non-safe selection",
    )

    report = {
        "query": QUERY,
        "request_task": "menu_planning",
        "plan": plan,
        "coverage_history": progress.get("coverage_history") or [],
        "final_coverage": progress.get("fulfilled"),
        "selected_count": len(names),
        "selected_names": names,
        "iterations": metadata.get("iteration"),
        "tool_call_count": metadata.get("tool_call_count"),
        "safety_review": metadata.get("safety_review"),
        "response": response.get("message"),
        "regressions": {
            "ordinary_recommendation": "passed",
            "simple_count_three": "passed",
            "small_composite_five": "passed",
            "persisted_peanut_allergy": "passed",
            "source_exhaustion": "covered_by_deterministic_reflector_test",
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
