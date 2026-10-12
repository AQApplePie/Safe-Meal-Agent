"""实现知识与菜谱检索基础设施适配。"""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from safemeal.modules.recipe.contracts.lookup import (
    RecipeCandidate,
    RecipeLookupResult,
)


_UNTRUSTED_INSTRUCTION = re.compile(
    r"ignore\s+(?:all\s+)?previous|system\s*prompt|tool\s*instruction|"
    r"忽略.{0,12}(?:指令|提示)|系统提示|工具指令",
    re.I,
)
_HEADING = re.compile(r"^={2,}\s*(.*?)\s*={2,}$")
_INGREDIENT_HEADINGS = {"材料", "食材", "原料", "配料", "ingredients"}
_STEP_HEADINGS = {"做法", "步骤", "制作", "烹饪", "procedure", "directions"}


# 方法说明：_clean_wikitext
# 作用：去除 Wiki 标记和无关模板，保留可解析的菜谱正文。
# 入参：
#   value（str）：当前待转换或校验的值。
#   limit（int）：本次查询或处理的最大条目数；默认值为 300。
# 出参：str；文本字符串。
def _clean_wikitext(value: str, *, limit: int = 300) -> str:
    text = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    text = re.sub(r"\{\{[^{}]{0,500}\}\}", "", text)
    text = re.sub(r"\[\[(?:[^]|]+\|)?([^]]+)\]\]", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"'{2,}", "", text)
    text = " ".join(text.split()).strip(" -*#;:")
    if _UNTRUSTED_INSTRUCTION.search(text):
        return ""
    return text[:limit]


# 方法说明：_section_rows
# 作用：从外部页面章节中提取可解析的条目行。
# 入参：
#   wikitext（str）：外部 Wiki 页面原始正文。
#   accepted（set[str]）：已接受的候选或数量。
# 出参：list[str]；菜谱章节中可解析的文本条目列表。
def _section_rows(wikitext: str, accepted: set[str]) -> list[str]:
    active = False
    rows: list[str] = []
    for raw in wikitext.splitlines()[:2000]:
        heading = _HEADING.match(raw.strip())
        if heading:
            title = _clean_wikitext(heading.group(1)).casefold()
            active = title in accepted
            continue
        if active and raw.lstrip().startswith(("*", "#")):
            value = _clean_wikitext(raw)
            if value:
                rows.append(value)
        if len(rows) >= 60:
            break
    return rows


# 方法说明：_ingredient
# 作用：把 Wiki 食材条目拆解为名称及用量字段。
# 入参：
#   value（str）：当前待转换或校验的值。
# 出参：dict[str, str]；包含食材名称及原始用量的字段映射。
def _ingredient(value: str) -> dict[str, str]:
    parts = re.split(r"\s*[：:]\s*|\s{2,}", value, maxsplit=1)
    return {
        "name": parts[0][:100],
        "amount": parts[1][:100] if len(parts) > 1 else "来源未标明",
        "section": "外部来源",
    }


# 方法说明：_title_leaf
# 作用：去除标题路径前缀，取得实际菜谱标题。
# 入参：
#   value（str）：当前待转换或校验的值。
# 出参：str；文本字符串。
def _title_leaf(value: str) -> str:
    return value.split(":")[-1].split("/")[-1].strip()


# 类说明（业务或基础设施实现类）：WikibooksRecipeProvider
# 作用：实现Wikibooks 菜谱来源适配器，封装该组件的业务处理与依赖协作。
class WikibooksRecipeProvider:
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 初始值：'wikibooks'。
    name = "wikibooks"
    # 字段说明：_HEADERS
    # 作用：HEADERS，供该组件初始化及运行控制使用。
    _HEADERS = {
        "User-Agent": "SafeMealAgent/0.1.2 (read-only recipe lookup)",
        "Accept": "application/json",
    }

    # 方法说明：__init__
    # 作用：初始化Wikibooks 菜谱来源适配器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   endpoint（str）：外部 API 的接口路径；默认值为 'https://zh.wikibooks.org/w/api.php'。
    #   timeout_seconds（float）：操作超时上限，单位秒；默认值为 8.0。
    #   client（httpx.Client | None）：底层外部服务客户端；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        *,
        endpoint: str = "https://zh.wikibooks.org/w/api.php",
        timeout_seconds: float = 8.0,
        client: httpx.Client | None = None,
    ) -> None:
        # 实例属性说明：_endpoint
        # 作用：外部 API 的接口路径。
        self._endpoint = endpoint
        # 实例属性说明：_timeout
        # 作用：操作超时上限，单位秒。
        self._timeout = timeout_seconds
        # 实例属性说明：_client
        # 作用：底层外部服务客户端。
        self._client = client

    # 方法说明：_request
    # 作用：向 Wiki API 发送查询并解析响应对象。
    # 入参：
    #   params（dict[str, str | int]）：底层接口使用的参数映射。
    # 出参：dict；外部 Wiki API 返回的解析对象。
    def _request(self, params: dict[str, str | int]) -> dict:
        if self._client is not None:
            response = self._client.get(
                self._endpoint, params=params, headers=self._HEADERS
            )
        else:
            with httpx.Client(
                timeout=self._timeout,
                follow_redirects=True,
                headers=self._HEADERS,
            ) as client:
                response = client.get(self._endpoint, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Wikibooks returned a non-object response")
        return payload

    # 方法说明：lookup
    # 作用：从配置的菜谱来源查找目标菜品及其食材证据。
    # 入参：
    #   recipe_name（str）：目标菜谱名称。
    # 出参：RecipeLookupResult；外部或本地菜谱查找结果。
    def lookup(self, recipe_name: str) -> RecipeLookupResult:
        query = recipe_name.strip()
        try:
            search = self._request(
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": f'intitle:"{query}"',
                    "srlimit": 5,
                    "format": "json",
                    "formatversion": 2,
                }
            )
            hits = search.get("query", {}).get("search", [])
            if not isinstance(hits, list) or not hits:
                return RecipeLookupResult(
                    status="NOT_FOUND", query=query, provider=self.name
                )
            normalized = re.sub(r"\W", "", query.casefold())
            titles = [
                str(hit.get("title") or "") for hit in hits if isinstance(hit, dict)
            ]
            titles = [title for title in titles if title]
            exact = [
                title
                for title in titles
                if re.sub(r"\W", "", _title_leaf(title).casefold()) == normalized
            ]
            title = (exact or titles)[0]
            parsed = self._request(
                {
                    "action": "parse",
                    "page": title,
                    "prop": "wikitext",
                    "format": "json",
                    "formatversion": 2,
                }
            )
            wikitext = parsed.get("parse", {}).get("wikitext", "")
            if not isinstance(wikitext, str):
                raise ValueError("Wikibooks page has no textual recipe content")
            ingredient_rows = _section_rows(wikitext, _INGREDIENT_HEADINGS)
            step_rows = _section_rows(wikitext, _STEP_HEADINGS)
            source_url = "https://zh.wikibooks.org/wiki/" + quote(
                title.replace(" ", "_"), safe=":/"
            )
            candidate = RecipeCandidate(
                name=query if exact else _clean_wikitext(_title_leaf(title)),
                ingredients=tuple(_ingredient(row) for row in ingredient_rows),
                steps="\n".join(step_rows)[:8000],
                source_type="wikibooks",
                source_url=source_url,
                source_title=title[:300],
                confidence=0.85 if exact else 0.65,
                persistent=False,
                ingredients_complete=bool(ingredient_rows),
            )
            return RecipeLookupResult(
                status="FOUND",
                query=query,
                provider=self.name,
                match_type="exact" if exact else "lexical",
                items=(candidate,),
            )
        except Exception as exc:
            return RecipeLookupResult(
                status="ERROR",
                query=query,
                provider=self.name,
                error=f"{type(exc).__name__}: {str(exc)[:300]}",
            )
