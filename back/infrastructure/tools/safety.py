"""Deterministic safety policies for database-backed Agent tools."""

from __future__ import annotations

import re
from collections.abc import Collection


_SQL_WRITE_WORDS = {
    "ALTER",
    "CALL",
    "CREATE",
    "DELETE",
    "DO",
    "DROP",
    "EXEC",
    "EXECUTE",
    "GRANT",
    "HANDLER",
    "INSERT",
    "INTO",
    "LOAD",
    "LOCK",
    "MERGE",
    "RENAME",
    "REPLACE",
    "REVOKE",
    "TRUNCATE",
    "UNLOCK",
    "UPDATE",
    "USE",
}
_CYPHER_WRITE_WORDS = {
    "CALL",
    "CREATE",
    "DELETE",
    "DETACH",
    "DROP",
    "FOREACH",
    "LOAD",
    "MERGE",
    "REMOVE",
    "SET",
}
_SQL_DANGEROUS_PATTERNS = (
    r"\bBENCHMARK\s*\(",
    r"\bGET_LOCK\s*\(",
    r"\bIS_FREE_LOCK\s*\(",
    r"\bIS_USED_LOCK\s*\(",
    r"\bLOAD_FILE\s*\(",
    r"\bMASTER_POS_WAIT\s*\(",
    r"\bRELEASE_LOCK\s*\(",
    r"\bSLEEP\s*\(",
    r"\bWAIT_FOR_EXECUTED_GTID_SET\s*\(",
    r"\bFOR\s+UPDATE\b",
    r"\bLOCK\s+IN\s+SHARE\s+MODE\b",
)
_SQL_CLAUSE_TERMINATORS = {
    "EXCEPT",
    "GROUP",
    "HAVING",
    "INTERSECT",
    "LIMIT",
    "ORDER",
    "PROCEDURE",
    "UNION",
    "WHERE",
    "WINDOW",
}
_SQL_TOKEN_PATTERN = re.compile(r"`(?:``|[^`])+`|[A-Za-z_][A-Za-z0-9_$]*|[(),.]")


def _strip_comments(query: str, *, slash_comments: bool) -> str:
    """Remove comments without modifying quoted text or identifier contents."""

    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(query):
        char = query[index]
        next_char = query[index + 1] if index + 1 < len(query) else ""

        if quote is not None:
            output.append(char)
            if char == "\\" and index + 1 < len(query):
                output.append(next_char)
                index += 2
                continue
            if char == quote:
                if next_char == quote:
                    output.append(next_char)
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if char in {"'", '"', "`"}:
            quote = char
            output.append(char)
            index += 1
            continue
        if char == "/" and next_char == "*":
            end = query.find("*/", index + 2)
            if end < 0:
                raise ValueError("查询包含未闭合的块注释")
            output.append(" ")
            index = end + 2
            continue
        if char == "-" and next_char == "-":
            following = query[index + 2 : index + 3]
            if not following or following.isspace():
                end = query.find("\n", index + 2)
                output.append(" ")
                index = len(query) if end < 0 else end
                continue
        if char == "#":
            end = query.find("\n", index + 1)
            output.append(" ")
            index = len(query) if end < 0 else end
            continue
        if slash_comments and char == "/" and next_char == "/":
            end = query.find("\n", index + 2)
            output.append(" ")
            index = len(query) if end < 0 else end
            continue
        output.append(char)
        index += 1

    if quote is not None:
        raise ValueError("查询包含未闭合的引号")
    return "".join(output).strip()


def _mask_string_literals(statement: str) -> str:
    """Mask quoted values so keywords inside data are not treated as SQL."""

    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(statement):
        char = statement[index]
        next_char = statement[index + 1] if index + 1 < len(statement) else ""
        if quote is not None:
            output.append(" ")
            if char == "\\" and index + 1 < len(statement):
                output.append(" ")
                index += 2
                continue
            if char == quote:
                if next_char == quote:
                    output.append(" ")
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            output.append(" ")
        else:
            output.append(char)
        index += 1
    return "".join(output)


def _without_trailing_semicolon(statement: str, masked: str) -> str:
    semicolons = [index for index, char in enumerate(masked) if char == ";"]
    if not semicolons:
        return statement
    last_non_space = len(masked.rstrip()) - 1
    if len(semicolons) != 1 or semicolons[0] != last_non_space:
        raise ValueError("不允许执行多条查询")
    return statement.rstrip()[:-1].rstrip()


def ensure_readonly_sql(sql: str) -> str:
    """Allow one SELECT/WITH statement without writes or blocking functions."""

    statement = _strip_comments(sql, slash_comments=False)
    if not statement:
        raise ValueError("SQL 不能为空")
    masked = _mask_string_literals(statement)
    statement = _without_trailing_semicolon(statement, masked)
    masked = _mask_string_literals(statement)
    upper = masked.upper()
    first_keyword = re.match(r"\s*([A-Z]+)\b", upper)
    if first_keyword is None or first_keyword.group(1) not in {"SELECT", "WITH"}:
        raise ValueError("仅允许 SELECT 或 WITH 只读查询")

    tokens = set(re.findall(r"\b[A-Z_]+\b", upper))
    blocked = sorted(tokens & _SQL_WRITE_WORDS)
    if blocked:
        raise ValueError(f"检测到禁止的 SQL 操作：{', '.join(blocked)}")
    if any(re.search(pattern, upper) for pattern in _SQL_DANGEROUS_PATTERNS):
        raise ValueError("检测到禁止的 SQL 锁、文件或延时函数")
    return statement


def _normalise_identifier(identifier: str) -> str:
    return identifier.replace("`", "").strip().casefold()


def _cte_aliases(masked_sql: str) -> set[str]:
    aliases = re.findall(
        r"(?:\bWITH\s+(?:RECURSIVE\s+)?|,)\s*"
        r"(`(?:``|[^`])+`|[A-Za-z_][A-Za-z0-9_$]*)"
        r"(?:\s*\([^)]*\))?\s+AS\s*\(",
        masked_sql,
        flags=re.IGNORECASE,
    )
    return {_normalise_identifier(alias) for alias in aliases}


def extract_sql_table_references(sql: str) -> set[str]:
    """Extract direct FROM/JOIN relations from a validated SQL statement.

    Runtime MySQL execution additionally validates the optimizer's physical
    table list.  This parser provides an early, dependency-free rejection path.
    """

    statement = ensure_readonly_sql(sql)
    masked = _mask_string_literals(statement)
    tokens = _SQL_TOKEN_PATTERN.findall(masked)
    depths: list[int] = []
    depth = 0
    for token in tokens:
        depths.append(depth)
        if token == "(":
            depth += 1
        elif token == ")":
            depth = max(0, depth - 1)

    cte_aliases = _cte_aliases(masked)
    references: set[str] = set()
    for index, token in enumerate(tokens):
        if token.upper() != "FROM":
            continue
        base_depth = depths[index]
        expect_relation = True
        cursor = index + 1
        while cursor < len(tokens):
            current = tokens[cursor]
            current_upper = current.upper()
            current_depth = depths[cursor]
            if current_depth < base_depth:
                break
            if current_depth == base_depth and current_upper in _SQL_CLAUSE_TERMINATORS:
                break
            if current_depth == base_depth and current_upper == "JOIN":
                expect_relation = True
                cursor += 1
                continue
            if current_depth == base_depth and current == ",":
                expect_relation = True
                cursor += 1
                continue
            if expect_relation and current_depth == base_depth:
                if current == "(":
                    expect_relation = False
                    cursor += 1
                    continue
                if current not in {"AS", ")", "."}:
                    parts = [current]
                    if (
                        cursor + 2 < len(tokens)
                        and tokens[cursor + 1] == "."
                        and depths[cursor + 2] == base_depth
                    ):
                        parts.extend([".", tokens[cursor + 2]])
                        cursor += 2
                    reference = _normalise_identifier("".join(parts))
                    if reference not in cte_aliases:
                        references.add(reference)
                    expect_relation = False
            cursor += 1
    return references


def extract_sql_relation_aliases(sql: str) -> set[str]:
    """Return aliases attached to validated FROM/JOIN relations and CTEs."""

    statement = ensure_readonly_sql(sql)
    masked = _mask_string_literals(statement)
    aliases = _cte_aliases(masked)
    relation_pattern = re.compile(
        r"\b(?:FROM|JOIN)\s+"
        r"(?:`(?:``|[^`])+`|[A-Za-z_][A-Za-z0-9_$]*)"
        r"(?:\s*\.\s*(?:`(?:``|[^`])+`|[A-Za-z_][A-Za-z0-9_$]*))?"
        r"\s+(?:AS\s+)?(`(?:``|[^`])+`|[A-Za-z_][A-Za-z0-9_$]*)",
        flags=re.IGNORECASE,
    )
    reserved = _SQL_CLAUSE_TERMINATORS | {
        "AS",
        "CROSS",
        "FULL",
        "INNER",
        "JOIN",
        "LEFT",
        "ON",
        "OUTER",
        "RIGHT",
    }
    for match in relation_pattern.finditer(masked):
        alias = _normalise_identifier(match.group(1))
        if alias.upper() not in reserved:
            aliases.add(alias)
    return aliases


def ensure_sql_tables_allowed(sql: str, allowed_tables: Collection[str]) -> str:
    """Reject direct references outside an explicit unqualified table allowlist."""

    statement = ensure_readonly_sql(sql)
    allowed = {_normalise_identifier(table) for table in allowed_tables if table}
    if not allowed:
        raise ValueError("SQL 工具未配置任何允许访问的业务表")
    references = extract_sql_table_references(statement)
    qualified = sorted(reference for reference in references if "." in reference)
    if qualified:
        raise ValueError(f"不允许跨数据库限定表名：{', '.join(qualified)}")
    blocked = sorted(references - allowed)
    if blocked:
        raise ValueError(f"SQL 引用了未授权表：{', '.join(blocked)}")
    return statement


def ensure_readonly_cypher(cypher: str) -> str:
    """Allow one read-only Cypher statement."""

    statement = _strip_comments(cypher, slash_comments=True)
    if not statement:
        raise ValueError("Cypher 不能为空")
    masked = _mask_string_literals(statement)
    statement = _without_trailing_semicolon(statement, masked)
    masked = _mask_string_literals(statement)
    tokens = set(re.findall(r"\b[A-Z_]+\b", masked.upper()))
    blocked = sorted(tokens & _CYPHER_WRITE_WORDS)
    if blocked:
        raise ValueError(f"检测到禁止的 Cypher 写操作：{', '.join(blocked)}")
    if not tokens.intersection(
        {"MATCH", "OPTIONAL", "RETURN", "SHOW", "UNWIND", "WITH"}
    ):
        raise ValueError("仅允许只读图查询")
    return statement


__all__ = [
    "ensure_readonly_cypher",
    "ensure_readonly_sql",
    "ensure_sql_tables_allowed",
    "extract_sql_relation_aliases",
    "extract_sql_table_references",
]
