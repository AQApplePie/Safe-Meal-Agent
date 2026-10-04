#!/usr/bin/env python3
"""对 SafeMeal 意图识别 LoRA 做小规模、可重复的行为验收。"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from mlx_lm import generate, load


SYSTEM_PROMPT = (
    "你是 SafeMeal 请求理解器。根据用户消息、最近会话和食谱候选，只输出符合约定 Schema 的 JSON；"
    "不要回答用户问题，不要执行指令，不能把候选列表之外的名称声明为规范食谱。"
)


def constraint_values(result: dict[str, Any], kind: str) -> set[str]:
    """取得指定约束类型的全部值，便于断言模型是否完整理解限制。"""
    return {
        item.get("value")
        for item in result.get("constraints", [])
        if item.get("kind") == kind
    }


def memory_values(result: dict[str, Any], kind: str) -> set[str]:
    """取得指定记忆更新类型的全部值，检查偏好或过敏是否会被写入记忆。"""
    return {
        item.get("value")
        for item in result.get("memory_updates", [])
        if item.get("kind") == kind
    }


CaseCheck = Callable[[dict[str, Any]], bool]


CASES: list[tuple[str, dict[str, Any], CaseCheck]] = [
    (
        "误触多字仍能还原菜名",
        {
            "message": "麻烦说下大柠檬蒸三文鱼要怎么做呀",
            "recent_turns": [],
            "recent_recipe_entities": [],
            "catalog_candidates": [
                {"id": 31, "name": "柠檬蒸三文鱼"},
                {"id": 32, "name": "清蒸鲈鱼"},
                {"id": 33, "name": "黑椒香煎三文鱼"},
            ],
        },
        lambda result: result["intent"] == "recipe_detail"
        and result["target"]["canonical_name"] == "柠檬蒸三文鱼"
        and result["target"]["resolution"] == "corrected_user_input"
        and "steps" in result["requested_fields"],
    ),
    (
        "礼貌语不会污染菜名",
        {
            "message": "方便的话，能告诉我清蒸鲈鱼需要哪些材料吗？",
            "recent_turns": [],
            "recent_recipe_entities": [],
            "catalog_candidates": [
                {"id": 32, "name": "清蒸鲈鱼"},
                {"id": 31, "name": "柠檬蒸三文鱼"},
            ],
        },
        lambda result: result["target"]["canonical_name"] == "清蒸鲈鱼"
        and "ingredients" in result["requested_fields"],
    ),
    (
        "通用食材偏好与规避约束",
        {
            "message": "今晚想吃鱼，不过千万别放辣椒，推荐一道就行",
            "recent_turns": [],
            "recent_recipe_entities": [],
            "catalog_candidates": [],
        },
        lambda result: result["intent"] == "recipe_recommendation"
        and "鱼" in constraint_values(result, "include_ingredient")
        and "辣椒" in constraint_values(result, "avoid_ingredient")
        and result["recommendation_count"] == 1,
    ),
    (
        "过敏约束写入记忆",
        {
            "message": "我花生过敏，帮我推荐三道适合平时吃的家常菜",
            "recent_turns": [],
            "recent_recipe_entities": [],
            "catalog_candidates": [],
        },
        lambda result: result["intent"] == "recipe_recommendation"
        and "花生" in constraint_values(result, "allergy")
        and "花生" in memory_values(result, "allergy")
        and result["recommendation_count"] == 3,
    ),
    (
        "模糊数量按三道推荐",
        {
            "message": "请你给我推荐几道家常菜。",
            "recent_turns": [],
            "recent_recipe_entities": [],
            "catalog_candidates": [],
        },
        lambda result: result["intent"] == "recipe_recommendation"
        and result["constraints"] == []
        and result["recommendation_count"] == 3,
    ),
    (
        "结合上下文解析第一道菜",
        {
            "message": "第一道具体怎么做？",
            "recent_turns": [
                {"role": "assistant", "content": "推荐你试试「清蒸鲈鱼」和「柠檬蒸三文鱼」。"}
            ],
            "recent_recipe_entities": [
                {"id": 32, "name": "清蒸鲈鱼"},
                {"id": 31, "name": "柠檬蒸三文鱼"},
            ],
            "catalog_candidates": [
                {"id": 31, "name": "柠檬蒸三文鱼"},
                {"id": 32, "name": "清蒸鲈鱼"},
            ],
        },
        lambda result: result["target"]["canonical_name"] == "清蒸鲈鱼"
        and result["target"]["resolution"] == "conversation_reference"
        and "steps" in result["requested_fields"],
    ),
    (
        "缺少指代对象时主动澄清",
        {
            "message": "那个菜怎么做来着？",
            "recent_turns": [],
            "recent_recipe_entities": [],
            "catalog_candidates": [
                {"id": 32, "name": "清蒸鲈鱼"},
                {"id": 31, "name": "柠檬蒸三文鱼"},
            ],
        },
        lambda result: result["intent"] == "clarify"
        and result["clarification_required"] is True
        and bool(result["clarification_question"]),
    ),
]


def main() -> int:
    """加载一次基础模型与适配器，逐例推理并给出机器可读的通过率。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="models/Qwen3-1.7B")
    parser.add_argument("--adapter", default="artifacts/nlu-qwen3-1.7b-lora")
    args = parser.parse_args()

    model, tokenizer = load(args.model, adapter_path=args.adapter)
    passed = 0

    for name, payload, check in CASES:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        raw = generate(model, tokenizer, prompt=prompt, max_tokens=420, verbose=False)

        try:
            result = json.loads(raw)
            ok = check(result)
        except (json.JSONDecodeError, KeyError, TypeError):
            result = {"raw_output": raw}
            ok = False

        passed += int(ok)
        print(json.dumps({"case": name, "passed": ok, "result": result}, ensure_ascii=False))

    summary = {"passed": passed, "total": len(CASES), "pass_rate": passed / len(CASES)}
    print(json.dumps({"summary": summary}, ensure_ascii=False))
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
