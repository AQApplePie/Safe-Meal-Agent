"""Live authenticated E2E for the stabilized first-version Agent contracts."""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:8000/api/v1"


def request_json(method, path, payload=None, token=None, timeout=360.0):
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
    email = f"contract-e2e-{unique}@example.com"
    password = "SafeMeal-Contract-2026"
    status, registered = request_json(
        "POST",
        "/auth/register",
        {"email": email, "password": password, "display_name": "Contract E2E"},
    )
    require(status == 201, f"register failed: {registered}")
    status, login = request_json(
        "POST", "/auth/login", {"email": email, "password": password}
    )
    require(status == 200, f"login failed: {login}")
    token = str(login["access_token"])

    def chat(message: str, case: str, session_id: str | None = None):
        payload: dict[str, Any] = {
            "message": message,
            "request_id": f"{case}-{unique}",
        }
        if session_id:
            payload["session_id"] = session_id
        chat_status, response = request_json("POST", "/chat/", payload, token)
        require(chat_status == 200, f"{case} failed: {response}")
        return response

    fish = chat("推荐四道鱼", "e2e1")
    fish_meta = fish["metadata"]
    fish_frame = fish_meta["request_frame"]
    fish_trace = next(
        item for item in fish_meta["tool_trace"] if item["tool"] == "recommend_recipes"
    )
    fish_names = fish_trace["result_names"]
    require(fish_frame["recommendation_count"] == 4, f"bad frame: {fish_frame}")
    require(fish_trace["args"]["requested_count"] == 4, f"bad args: {fish_trace}")
    require(fish_trace["args"]["food_categories"] == ["fish"], "fish filter lost")
    require(len(fish_names) == 4, f"expected four fish: {fish_names}")
    require(
        all(re.search(r"鱼|鲈|鳕|鲑", name) for name in fish_names),
        f"non-fish result published: {fish_names}",
    )
    require(fish_meta["reflect"]["evidence_sufficient"] is True, "4/4 incomplete")

    menu = chat("给四个人安排两荤两素一汤", "e2e2")
    menu_meta = menu["metadata"]
    menu_frame = menu_meta["request_frame"]
    menu_progress = menu_meta["menu_task_progress"]
    require(menu_frame["servings"] == 4, f"servings lost: {menu_frame}")
    require(
        menu_progress["fulfilled"] == {"meat": 2, "vegetarian": 2, "soup": 1},
        f"quota incomplete: {menu_progress}",
    )
    menu_names = [item["name"] for item in menu_progress["selected_recipes"]]
    require(len(menu_names) == len(set(menu_names)) == 5, f"duplicates: {menu_names}")

    detail = chat("柠檬蒸三文鱼怎么做", "e2e3")
    detail_frame = detail["metadata"]["request_frame"]
    require(detail_frame["target"]["recipe_name"] == "柠檬蒸三文鱼", "bad target")
    require(detail_frame["requested_fields"] == ["steps"], "steps field lost")
    require("的做法" in detail["message"], f"steps not returned: {detail['message']}")
    require("的材料" not in detail["message"], "ingredients substituted for steps")

    first = chat("推荐一道鱼", "e2e4-first")
    follow = chat("具体怎么做？", "e2e4-follow", first["session_id"])
    follow_frame = follow["metadata"]["request_frame"]
    require(follow_frame["requested_fields"] == ["steps"], "follow-up lost steps")
    require(bool(follow_frame["target"]["recipe_name"]), "follow-up target unresolved")
    require("的做法" in follow["message"], f"follow-up failed: {follow['message']}")

    allergy = chat("我对花生过敏，有没有不含花生的菜", "e2e5")
    allergy_meta = allergy["metadata"]
    allergy_frame = allergy_meta["request_frame"]
    require(allergy_frame["tasks"][0]["kind"] == "recipe_recommendation", "task lost")
    require(
        any(
            item["kind"] == "allergy" and item["value"] == "花生"
            for item in allergy_frame["memory_updates"]
        ),
        "allergy memory update lost",
    )
    require(allergy_meta["safety_review"] == "passed", "current safety failed")
    status, memories = request_json("GET", "/chat/memories", token=token)
    require(status == 200, f"memory lookup failed: {memories}")
    require(any(item.get("memory_key") == "花生" for item in memories), "memory not saved")

    report = {
        "E2E1": {"request_frame": fish_frame, "planner_tool": fish_trace, "reflect": fish_meta["reflect"], "final_response": fish["message"], "all_fish": True},
        "E2E2": {"request_frame": menu_frame, "coverage": menu_progress["fulfilled"], "selected": menu_names, "final_response": menu["message"]},
        "E2E3": {"request_frame": detail_frame, "final_response": detail["message"]},
        "E2E4": {"request_frame": follow_frame, "final_response": follow["message"]},
        "E2E5": {"request_frame": allergy_frame, "resolved_constraints": allergy_meta["resolved_constraints"], "final_safety": allergy_meta["safety_review"], "memory_saved": True, "final_response": allergy["message"]},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
