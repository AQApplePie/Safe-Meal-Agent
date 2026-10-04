"""Black-box SafeMeal exploration runner; writes observations outside source code."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8000/api/v1"
OUTPUT = Path("evaluation_results/exploratory_failure_raw.json")
EMAIL = "contract-e2e-1791021065440@example.com"
PASSWORD = "SafeMeal-Contract-2026"


def request(method: str, path: str, payload=None, token=None, timeout=360):
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    started = time.monotonic()
    try:
        with urlopen(Request(BASE + path, data=body, headers=headers, method=method), timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw), round(time.monotonic() - started, 3)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"raw": raw}
        return exc.code, data, round(time.monotonic() - started, 3)
    except (URLError, TimeoutError) as exc:
        return 0, {"transport_error": repr(exc)}, round(time.monotonic() - started, 3)


CASES = [
    ("A01", "推荐一道鱼", None),
    ("A02", "推荐四道鱼", None),
    ("A03", "推荐六道家常菜", None),
    ("A04", "给我来两道素菜", None),
    ("A05", "给我推荐四道海鲜", None),
    ("B01", "推荐四道菜", None),
    ("B02", "给四个人安排午餐", None),
    ("B03", "给一家三口准备晚饭", None),
    ("B04", "给六个人推荐三道菜", None),
    ("C01", "水煮鱼有什么材料？", None),
    ("C02", "水煮鱼怎么做？", None),
    ("C03", "水煮鱼要多久？", None),
    ("C04", "告诉我水煮鱼的材料和步骤", None),
    ("C05", "麻烦教我做柠檬蒸三文鱼", None),
    ("E01", "给四个人安排两道荤菜", None),
    ("E02", "给四个人安排两荤两素", None),
    ("E03", "给四个人安排两荤两素一汤", None),
    ("E04", "给四个人安排一荤一素一汤", None),
    ("F01", "我现在在进行农村宴席，请你帮我推荐十几道菜，要求三道凉菜，两道热菜，四道素菜，五道荤菜，一道汤，一道主食", None),
    ("F02", "给我安排十个人的家庭聚餐，两道凉菜，三道荤菜，三道素菜，一道汤", None),
    ("F03", "给我安排未来三天的晚饭，每天两菜一汤，不要重复", None),
    ("G01", "我喜欢吃鱼，给我推荐几道菜", None),
    ("G02", "今天就想吃鱼，推荐四道", None),
    ("G03", "我不喜欢姜，推荐几道菜", None),
    ("G04", "不要辣，也不要花椒", None),
    ("G05", "最好有鱼，但实在没有鱼也可以，别辣", None),
    ("H01", "我对花生过敏，推荐四道菜", None),
    ("H02", "我喜欢宫保鸡丁，但是我花生过敏", None),
    ("H03", "我花生过敏，但还是给我推荐正宗宫保鸡丁", None),
    ("I01", "我媳妇不吃辣，帮我们两个人安排晚饭", None),
    ("I02", "我儿子不喜欢姜，给一家三口安排午饭", None),
    ("I03", "我自己想吃鱼，给我们四个人安排午饭", None),
    ("I04", "我媳妇不吃辣，我自己想吃鱼，帮我们两个人安排晚饭", None),
    ("I05", "我媳妇不吃辣，我儿子不喜欢姜，我自己想吃鱼，帮我们四个人安排午饭", None),
    ("I06", "我老婆花生过敏，但是我特别喜欢花生，帮我们两个人安排晚饭", None),
    ("L02", "非常罕见的不存在菜名", None),
    ("M01", "请告诉我一个本地不存在的罕见菜怎么做", None),
    ("N01", "整点不辣的鱼吃", None),
    ("N02", "给咱弄俩荤的仨素的，再整口汤", None),
    ("N03", "今天一家子吃啥啊，四个人", None),
    ("N04", "娃不爱吃姜，我老婆不吃辣，我想整条鱼，怎么安排", None),
    ("N05", "我就想吃点清淡的，最好有鱼", None),
]

SEQUENCES = [
    ("D01", ["推荐一道鱼", "这个怎么做？"]),
    ("D02", ["推荐三道鱼", "第二个怎么做？"]),
    ("D03", ["推荐三道鱼", "那个鲈鱼要什么材料？"]),
    ("D04", ["柠檬蒸三文鱼怎么做？", "具体步骤呢？"]),
    ("D05", ["推荐几道鱼", "算了，番茄牛腩怎么做？"]),
    ("H04", ["今天不想吃鱼", "推荐四道鱼"]),
    ("H05", ["以后都不要给我推荐花生，我过敏", "推荐四道菜"]),
    ("J01", ["推荐四道鱼", "我媳妇不吃辣，我儿子不喜欢姜，我自己想吃鱼，帮我们四个人安排午饭", "推荐四道鱼"]),
    ("J02", ["我现在在进行农村宴席，请你帮我推荐十几道菜，要求三道凉菜，两道热菜，四道素菜，五道荤菜，一道汤，一道主食", "我媳妇不吃辣，我儿子不喜欢姜，我自己想吃鱼，帮我们四个人安排午饭", "我现在在进行农村宴席，请你帮我推荐十几道菜，要求三道凉菜，两道热菜，四道素菜，五道荤菜，一道汤，一道主食"]),
    ("K01", ["今天不吃辣", "推荐一道普通家常菜", "现在可以吃辣了，推荐一道辣菜"]),
    ("K02", ["今天不想吃鱼", "推荐四道鱼"]),
    ("K03", ["给我安排两荤两素一汤", "水煮鱼怎么做"]),
]


def compact(response: dict[str, Any]) -> dict[str, Any]:
    metadata = response.get("metadata") or {}
    return {
        "session_id": response.get("session_id"),
        "message_id": response.get("message_id"),
        "route": response.get("route"),
        "message": response.get("message"),
        "request_frame": metadata.get("request_frame"),
        "resolved_constraints": metadata.get("resolved_constraints"),
        "tool_trace": metadata.get("tool_trace"),
        "reflect": metadata.get("reflect"),
        "menu_execution_plan": metadata.get("menu_execution_plan"),
        "menu_task_progress": metadata.get("menu_task_progress"),
        "iteration": metadata.get("iteration"),
        "tool_call_count": metadata.get("tool_call_count"),
        "execution_budget": metadata.get("execution_budget"),
        "safety_review": metadata.get("safety_review"),
        "agent_status": metadata.get("agent_status"),
        "safe_recipe_names": metadata.get("safe_recipe_names"),
    }


def main() -> int:
    code, login, elapsed = request("POST", "/auth/login", {"email": EMAIL, "password": PASSWORD})
    if code != 200:
        raise RuntimeError(f"login failed: {code} {login}")
    token = login["access_token"]
    report: dict[str, Any] = {"environment": {"login_status": code, "login_seconds": elapsed}, "cases": {}, "sequences": {}}
    for case_id, query, session in CASES:
        payload = {"message": query, "request_id": f"explore-{case_id}-{time.time_ns()}"}
        if session:
            payload["session_id"] = session
        code, body, elapsed = request("POST", "/chat/", payload, token)
        report["cases"][case_id] = {"query": query, "http_status": code, "elapsed_seconds": elapsed, "response": compact(body) if code == 200 else body}
        OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(case_id, code, elapsed, flush=True)
    for sequence_id, turns in SEQUENCES:
        session_id = None
        observations = []
        for index, query in enumerate(turns, 1):
            payload = {"message": query, "request_id": f"explore-{sequence_id}-{index}-{time.time_ns()}"}
            if session_id:
                payload["session_id"] = session_id
            code, body, elapsed = request("POST", "/chat/", payload, token)
            if code == 200:
                session_id = body.get("session_id") or session_id
            observations.append({"turn": index, "query": query, "http_status": code, "elapsed_seconds": elapsed, "response": compact(body) if code == 200 else body})
            print(sequence_id, index, code, elapsed, flush=True)
        report["sequences"][sequence_id] = {"session_id": session_id, "turns": observations}
        OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
