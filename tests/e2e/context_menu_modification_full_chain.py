"""Real HTTP/SSE regression for persisted active-menu modifications.

Run against the local Docker API:
    python tests/e2e/context_menu_modification_full_chain.py
"""

from __future__ import annotations

import json
import time
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:8000/api/v1"
BANQUET = (
    "我现在在进行农村宴席，请你帮我推荐十几道菜，要求三道凉菜，"
    "两道热菜，四道素菜，五道荤菜，一道汤，一道主食"
)
EXPECTED = {
    "cold_dish": 3,
    "hot_dish": 2,
    "vegetarian": 4,
    "meat": 5,
    "soup": 1,
    "staple": 1,
}


def request(method: str, path: str, payload=None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(
        Request(
            BASE_URL + path,
            data=json.dumps(payload, ensure_ascii=False).encode() if payload else None,
            headers=headers,
            method=method,
        ),
        timeout=360,
    ) as response:
        return json.loads(response.read())


def chat(token: str, message: str, session_id: str | None = None):
    payload = {"message": message, "request_id": str(time.time_ns())}
    if session_id:
        payload["session_id"] = session_id
    return request("POST", "/chat/", payload, token)


def stream_chat(token: str, message: str, session_id: str):
    payload = {
        "message": message,
        "session_id": session_id,
        "request_id": str(time.time_ns()),
    }
    raw = (
        urlopen(
            Request(
                BASE_URL + "/chat/stream",
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            ),
            timeout=360,
        )
        .read()
        .decode()
    )
    events = []
    for block in raw.split("\n\n"):
        lines = block.splitlines()
        event = next((line[7:] for line in lines if line.startswith("event: ")), None)
        data = next((line[6:] for line in lines if line.startswith("data: ")), None)
        if event and data:
            events.append((event, json.loads(data)))
    completed = next(data for event, data in events if event == "done")
    return completed, [event for event, _ in events]


def selected(metadata: dict, category: str | None = None):
    rows = metadata["active_menu"]["progress"]["selected_recipes"]
    return [
        row for row in rows if category is None or row["assigned_category"] == category
    ]


def category_snapshot(metadata: dict, excluded: str):
    return {
        category: [row["recipe_id"] for row in selected(metadata, category)]
        for category in EXPECTED
        if category != excluded
    }


def main() -> None:
    nonce = time.time_ns()
    credentials = {
        "email": f"context-menu-{nonce}@example.com",
        "password": "SafeMeal-Context-2026",
        "display_name": "Context Menu E2E",
    }
    request("POST", "/auth/register", credentials)
    token = request(
        "POST",
        "/auth/login",
        {"email": credentials["email"], "password": credentials["password"]},
    )["access_token"]

    first = chat(token, BANQUET)
    first_metadata = first["metadata"]
    assert first_metadata["menu_task_progress"]["fulfilled"] == EXPECTED
    assert len(selected(first_metadata)) == 16
    old_meat_ids = {row["recipe_id"] for row in selected(first_metadata, "meat")}
    untouched = category_snapshot(first_metadata, "meat")

    second, sse_events = stream_chat(token, "重新推荐荤菜", first["session_id"])
    second_metadata = second["metadata"]
    frame = second_metadata["request_frame"]
    new_meats = selected(second_metadata, "meat")
    new_meat_ids = {row["recipe_id"] for row in new_meats}
    trace = second_metadata["tool_trace"][0]
    assert frame["context_relation"] == "modification"
    assert frame["operation"] == "replace"
    assert frame["target"]["menu_category"] == "meat"
    assert frame["recommendation_count"] == 5
    assert len(new_meats) == 5
    assert all(row["assigned_category"] == "meat" for row in new_meats)
    assert old_meat_ids.isdisjoint(new_meat_ids)
    assert old_meat_ids.issubset(set(trace["args"]["exclude_recipe_ids"]))
    assert category_snapshot(second_metadata, "meat") == untouched
    assert len({row["name"] for row in selected(second_metadata)}) == 16
    assert "done" in sse_events and "answer" in sse_events

    matrix_results = {}
    cases = (
        ("CM02", "重新推荐素菜", "vegetarian", 4),
        ("CM03", "汤换一个", "soup", 1),
        ("CM04", "荤菜改成三道", "meat", 3),
        ("CM05", "荤菜不要鸡肉，重新推荐", "meat", 5),
        ("CM06", "素菜保留，荤菜重新推荐", "meat", 5),
    )
    for case_id, query, category, count in cases:
        original = chat(token, BANQUET)
        original_meta = original["metadata"]
        old_ids = {row["recipe_id"] for row in selected(original_meta, category)}
        unchanged = category_snapshot(original_meta, category)
        changed = chat(token, query, original["session_id"])
        changed_meta = changed["metadata"]
        changed_frame = changed_meta["request_frame"]
        replacements = selected(changed_meta, category)
        assert changed_frame["context_relation"] == "modification"
        assert changed_frame["operation"] == "replace"
        assert changed_frame["target"]["menu_category"] == category
        assert changed_frame["recommendation_count"] == count
        assert len(replacements) == count
        assert old_ids.isdisjoint({row["recipe_id"] for row in replacements})
        assert category_snapshot(changed_meta, category) == unchanged
        if case_id == "CM05":
            effective = changed_meta["tool_trace"][0]["effective_args"]
            assert "鸡肉" in effective["exclude_ingredients"]
            assert "鸡腿肉" in effective["exclude_ingredients"]
        matrix_results[case_id] = "PASS"

    reference_menu = chat(token, BANQUET)
    expected_reference = selected(reference_menu["metadata"], "meat")[1]["name"]
    reference = chat(token, "第二道荤菜怎么做？", reference_menu["session_id"])
    reference_frame = reference["metadata"]["request_frame"]
    assert reference_frame["context_relation"] == "reference"
    assert reference_frame["target"]["recipe_name"] == expected_reference
    assert (
        reference["metadata"]["active_menu"]
        == reference_menu["metadata"]["active_menu"]
    )
    matrix_results["REFERENCE"] = "PASS"

    fish = chat(token, "推荐四道鱼", first["session_id"])
    fish_frame = fish["metadata"]["request_frame"]
    assert fish_frame["context_relation"] == "new_task"
    assert fish_frame["recommendation_count"] == 4

    detail = chat(token, "水煮鱼怎么做", first["session_id"])
    detail_frame = detail["metadata"]["request_frame"]
    assert detail_frame["target"]["recipe_name"] == "水煮鱼"
    assert detail_frame["requested_fields"] == ["steps"]

    compact = chat(token, "两荤两素一汤")
    assert compact["metadata"]["menu_task_progress"]["fulfilled"] == {
        "meat": 2,
        "vegetarian": 2,
        "soup": 1,
    }

    three_fish = chat(token, "推荐三道鱼")
    fish_rows = three_fish["metadata"]["tool_trace"][0]["result_names"]
    second_fish = chat(token, "第二个怎么做", three_fish["session_id"])
    assert (
        second_fish["metadata"]["request_frame"]["target"]["recipe_name"]
        == fish_rows[1]
    )
    assert "的做法" in second_fish["message"]

    history = request("GET", f"/chat/history/{first['session_id']}", token=token)
    result = {
        "session_id": first["session_id"],
        "conversation_id": first["session_id"],
        "turn_1_message_id": first["message_id"],
        "turn_2_message_id": second["message_id"],
        "history_message_ids": [row["id"] for row in history],
        "turn_1_coverage": EXPECTED,
        "turn_1_total": 16,
        "turn_2_requested": 5,
        "turn_2_returned": len(new_meats),
        "old_meat_ids": sorted(old_meat_ids),
        "new_meat_ids": sorted(new_meat_ids),
        "overlap": sorted(old_meat_ids & new_meat_ids),
        "untouched_categories_preserved": True,
        "sse_events": sse_events,
        "new_task_isolation": True,
        "context_matrix": matrix_results,
        "regressions": {
            "four_fish": "PASS",
            "recipe_detail": "PASS",
            "two_meat_two_vegetarian_one_soup": "PASS",
            "banquet_16": "PASS",
            "banquet_then_recipe_detail": "PASS",
            "three_fish_then_second_detail": "PASS",
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
