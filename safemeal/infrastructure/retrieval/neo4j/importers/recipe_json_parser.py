"""
用于菜谱知识图谱引导的共享数据解析工具。
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from safemeal.shared.types import JsonObject, to_json_object


# 类说明（数据契约类）：IngredientAmount
# 作用：描述食材用量文本结构的结构、类型及可校验字段。
@dataclass
class IngredientAmount:
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：str。
    name: str
    # 字段说明：amount
    # 作用：食材用量数值，计量单位由 unit 指定。
    # 类型：Optional[str]。
    amount: Optional[str]
    # 字段说明：role
    # 作用：食材在菜谱中的角色，例如主料、辅料或调味料。
    # 类型：str。
    role: str


# 类说明（数据契约类）：StepRecord
# 作用：描述图导入烹饪步骤记录的结构、类型及可校验字段。
@dataclass
class StepRecord:
    # 字段说明：order
    # 作用：对象在当前列表或会话内的顺序位置。
    # 类型：int。
    order: int
    # 字段说明：instruction
    # 作用：传递给执行器或模型的具体任务指令。
    # 类型：str。
    instruction: str


# 类说明（数据契约类）：RecipeRecord
# 作用：描述图导入菜谱记录的结构、类型及可校验字段。
@dataclass
class RecipeRecord:
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：str。
    name: str
    # 字段说明：cook_time
    # 作用：制作或执行所需时间，单位为分钟。
    # 类型：Optional[str]。
    cook_time: Optional[str]
    # 字段说明：flavors
    # 作用：口味标签或要求，用于偏好评估与候选排序。
    # 类型：List[str]。
    flavors: List[str]
    # 字段说明：methods
    # 作用：组件支持的操作或 HTTP 方法集合。
    # 类型：List[str]。
    methods: List[str]
    # 字段说明：dish_types
    # 作用：菜品或食材的分类标签，参与过滤与菜单配额判断。
    # 类型：List[str]。
    dish_types: List[str]
    # 字段说明：instructions
    # 作用：当前调用的业务指令文本。
    # 类型：Optional[str]。
    instructions: Optional[str]
    # 字段说明：steps
    # 作用：菜谱制作步骤，按执行顺序排列。
    # 类型：List[StepRecord]。
    steps: List[StepRecord]
    # 字段说明：main_ingredients
    # 作用：菜谱主料集合。
    # 类型：List[IngredientAmount]。
    main_ingredients: List[IngredientAmount]
    # 字段说明：aux_ingredients
    # 作用：配料或辅料集合，参与完整食材与过敏检查。
    # 类型：List[IngredientAmount]。
    aux_ingredients: List[IngredientAmount]
    # 字段说明：ingredient_data_complete
    # 作用：食材清单是否完整，缺失时不能给出确定的安全结论。
    # 类型：bool。
    ingredient_data_complete: bool


# 类说明（数据契约类）：IngredientProfile
# 作用：描述食材营养与功效资料的结构、类型及可校验字段。
@dataclass
class IngredientProfile:
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：str。
    name: str
    # 字段说明：nutrition
    # 作用：菜谱或食材的结构化营养信息。
    # 类型：Optional[str]。
    nutrition: Optional[str]
    # 字段说明：benefits
    # 作用：检索资料或分析给出的潜在益处说明。
    # 类型：List[str]。
    benefits: List[str]


# 方法说明：load_recipe_records
# 作用：从 JSON 映射中加载结构化的菜谱记录。
# 入参：
#   recipe_json（Path）：菜谱 JSON 数据路径。
# 出参：Tuple[List[RecipeRecord], Set[str]]；图导入菜谱记录的集合、文本字符串的集合组成的元组。
def load_recipe_records(recipe_json: Path) -> Tuple[List[RecipeRecord], Set[str]]:
    """从 JSON 映射中加载结构化的菜谱记录。"""
    payload = _load_json(recipe_json)
    return _normalize_recipes(payload)


# 方法说明：load_ingredient_profiles
# 作用：返回食谱中所用食材的营养成分表。
# 入参：
#   ingredient_json（Optional[Path]）：食材营养与分类 JSON 数据路径。
#   ingredients_used（Set[str]）：菜谱使用的完整食材集合。
# 出参：List[IngredientProfile]；食材营养与功效资料的集合。
def load_ingredient_profiles(
    ingredient_json: Optional[Path],
    ingredients_used: Set[str],
) -> List[IngredientProfile]:
    """返回食谱中所用食材的营养成分表。"""
    if not ingredient_json or not ingredient_json.is_file():
        return []

    payload = _load_json(ingredient_json)
    profiles: List[IngredientProfile] = []
    for name in sorted(ingredients_used):
        raw = payload.get(name)
        if not isinstance(raw, dict):
            continue
        nutrition = _clean_text(raw.get("营养价值"))
        benefits = _split_benefits(_clean_text(raw.get("食用功效")))
        profiles.append(
            IngredientProfile(name=name, nutrition=nutrition, benefits=benefits)
        )
    return profiles


# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 方法说明：_load_json
# 作用：读取并解析本地 JSON 数据文件。
# 入参：
#   path（Path）：本次读取或写入的路径。
# 出参：JsonObject；JSON 字段映射。
def _load_json(path: Path) -> JsonObject:
    if not path.is_file():
        raise FileNotFoundError(f"JSON dataset not found: {path}")
    with path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected top-level object to be a dict in {path}")
    return to_json_object(payload)


# 方法说明：_normalize_recipes
# 作用：将外部菜谱响应统一为内部菜谱模型。
# 入参：
#   recipes_raw（JsonObject）：尚未完成归一化的外部原始数据。
# 出参：Tuple[List[RecipeRecord], Set[str]]；图导入菜谱记录的集合、文本字符串的集合组成的元组。
def _normalize_recipes(
    recipes_raw: JsonObject,
) -> Tuple[List[RecipeRecord], Set[str]]:
    records: List[RecipeRecord] = []
    ingredients_seen: Set[str] = set()

    for raw_name, payload in recipes_raw.items():
        if not isinstance(payload, dict):
            continue

        name = _clean_name(raw_name)
        cook_time = _clean_text(payload.get("耗时"))
        flavors = _split_multi(payload.get("口味"))
        methods = _split_multi(payload.get("工艺"))
        dish_types = _split_multi(payload.get("类型"))
        instructions = _clean_text(payload.get("做法"))

        main_ingredients = _normalize_ingredients(
            payload.get("主食材"),
            role="main",
            seen=ingredients_seen,
        )
        aux_ingredients = _normalize_ingredients(
            payload.get("辅料"),
            role="aux",
            seen=ingredients_seen,
        )
        steps = _normalize_steps(instructions)
        ingredient_data_complete = isinstance(
            payload.get("主食材"), list
        ) and isinstance(payload.get("辅料"), list)

        records.append(
            RecipeRecord(
                name=name,
                cook_time=cook_time,
                flavors=flavors,
                methods=methods,
                dish_types=dish_types,
                instructions=instructions,
                steps=steps,
                main_ingredients=main_ingredients,
                aux_ingredients=aux_ingredients,
                ingredient_data_complete=ingredient_data_complete,
            ),
        )

    return records, ingredients_seen


# 方法说明：_clean_name
# 作用：清理并归一化名称，统一名称比较与去重。
# 入参：
#   value（object）：当前待转换或校验的值。
# 出参：str；文本字符串。
def _clean_name(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


# 方法说明：_clean_text
# 作用：清理外部文本中的空白与格式噪声。
# 入参：
#   value（object）：当前待转换或校验的值。
# 出参：Optional[str]；文本字符串或 None。
def _clean_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# 方法说明：_split_multi
# 作用：拆分包含多个值的文本并清理空项。
# 入参：
#   value（object）：当前待转换或校验的值。
# 出参：List[str]；拆分并清理后的非空文本列表。
def _split_multi(value: object) -> List[str]:
    if not value:
        return []
    text = str(value)
    parts = re.split(r"[、/,，；;]+", text)
    return [part.strip() for part in parts if part.strip()]


# 方法说明：_normalize_ingredients
# 作用：归一化原始食材列表，形成稳定的食材字段。
# 入参：
#   value（object）：当前待转换或校验的值。
#   role（str）：消息角色或用户角色名称。
#   seen（Set[str]）：已处理条目的去重集合。
# 出参：List[IngredientAmount]；食材用量文本结构的集合。
def _normalize_ingredients(
    value: object,
    *,
    role: str,
    seen: Set[str],
) -> List[IngredientAmount]:
    result: List[IngredientAmount] = []
    items: Iterable[object]
    if isinstance(value, list):
        items = value
    else:
        items = []

    for item in items:
        if isinstance(item, (list, tuple)) and item:
            name = _clean_name(item[0])
            amount = _clean_text(item[1]) if len(item) > 1 else None
        elif isinstance(item, str):
            name = _clean_name(item)
            amount = None
        else:
            continue
        if not name:
            continue
        seen.add(name)
        result.append(IngredientAmount(name=name, amount=amount, role=role))
    return result


# 方法说明：_normalize_steps
# 作用：将原始做法转换为有序的烹饪步骤。
# 入参：
#   instructions（Optional[str]）：当前调用的业务指令文本。
# 出参：List[StepRecord]；图导入烹饪步骤记录的集合。
def _normalize_steps(instructions: Optional[str]) -> List[StepRecord]:
    if not instructions:
        return []

    normalized = instructions.replace("：", ":")
    pattern = re.compile(r"(?P<order>\d+):\s*(?P<text>.*?)(?=(?:\d+:)|$)", re.S)
    matches = list(pattern.finditer(normalized))

    steps: List[StepRecord] = []
    if matches:
        for match in matches:
            order = int(match.group("order"))
            text = match.group("text").strip().rstrip("。.")
            if text:
                steps.append(StepRecord(order=order, instruction=text))
    else:
        fragments = re.split(r"[。.!？！\n]+", normalized)
        filtered = [fragment.strip() for fragment in fragments if fragment.strip()]
        for index, fragment in enumerate(filtered, start=1):
            steps.append(StepRecord(order=index, instruction=fragment))
    return steps


# 方法说明：_split_benefits
# 作用：拆分食材功效文本，形成图导入属性。
# 入参：
#   text（Optional[str]）：待解析、检索、切分或渲染的文本。
# 出参：List[str]；拆分并清理后的非空文本列表。
def _split_benefits(text: Optional[str]) -> List[str]:
    if not text:
        return []
    lines = re.split(r"[\n\r]+", text)
    benefits: List[str] = []
    for line in lines:
        cleaned = line.strip()
        cleaned = re.sub(r"^[0-9]+[\\.、:：)\s]*", "", cleaned)
        if cleaned:
            benefits.append(cleaned)
    return benefits
