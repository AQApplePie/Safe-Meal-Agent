"""实现知识与菜谱检索基础设施适配。"""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from safemeal.application.contracts.recipes.lookup import (
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


def _ingredient(value: str) -> dict[str, str]:
    parts = re.split(r"\s*[：:]\s*|\s{2,}", value, maxsplit=1)
    return {
        "name": parts[0][:100],
        "amount": parts[1][:100] if len(parts) > 1 else "来源未标明",
        "section": "外部来源",
    }


def _title_leaf(value: str) -> str:
    return value.split(":")[-1].split("/")[-1].strip()


class WikibooksRecipeProvider:
    name = "wikibooks"
    _HEADERS = {
        "User-Agent": "SafeMealAgent/0.1.2 (read-only recipe lookup)",
        "Accept": "application/json",
    }

    def __init__(
        self,
        *,
        endpoint: str = "https://zh.wikibooks.org/w/api.php",
        timeout_seconds: float = 8.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._timeout = timeout_seconds
        self._client = client

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
