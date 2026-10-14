"""检查核心后端类、字段、枚举值及方法的中文说明完整性。"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path


def comment_block(lines: list[str], node: ast.AST) -> str:
    """取得定义及其装饰器前的注释块。

    入参：lines 为文件行列表，node 为类或函数 AST 节点。
    出参：连续注释组成的文本；没有注释时为空字符串。
    """
    start = min(
        [getattr(node, "lineno")]
        + [decorator.lineno for decorator in getattr(node, "decorator_list", [])]
    )
    position = start - 2
    comments: list[str] = []
    while position >= 0 and lines[position].lstrip().startswith("#"):
        comments.append(lines[position].strip())
        position -= 1
    return "\n".join(reversed(comments))


def literal_members(node: ast.AST | None) -> list[str]:
    """取得类型表达式中直接声明的 Literal 字符串成员。

    入参：node 为类型表达式节点；None 表示没有显式类型注解。
    出参：成员文本列表；类型别名由 audit 另外解析。
    """
    if node is None:
        return []
    return [
        member.value
        for component in ast.walk(node)
        if isinstance(component, ast.Subscript)
        and ast.unparse(component.value) == "Literal"
        for member in ast.walk(component.slice)
        if isinstance(member, ast.Constant) and isinstance(member.value, str)
    ]


def audit(root: Path) -> dict[str, object]:
    """检查 safemeal 包的类作用、SQL 标识及方法参数和返回说明。

    入参：root 为项目根目录。
    出参：含文件数、类数、方法数、SQL 类数和缺漏列表的检查结果。
    """
    files = sorted((root / "safemeal").rglob("*.py"))
    classes = methods = sql_classes = 0
    fields = instance_attributes = literal_values = 0
    issues: list[str] = []
    aliases: dict[str, list[str]] = {}
    for path in files:
        for definition in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(definition, ast.Assign):
                choices = literal_members(definition.value)
                for target in definition.targets:
                    if isinstance(target, ast.Name) and choices:
                        aliases[target.id] = choices
            elif isinstance(definition, ast.ClassDef) and any(
                ast.unparse(base).endswith("Enum") for base in definition.bases
            ):
                aliases[definition.name] = [
                    statement.value.value
                    for statement in definition.body
                    if isinstance(statement, ast.Assign)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)
                ]
    for path in files:
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            block = comment_block(lines, node)
            label = f"{path.relative_to(root)}:{node.lineno} {node.name}"
            purpose = re.search(r"# 作用：([^\n]+)", block)
            if not purpose or not re.search(r"[\u4e00-\u9fff]", purpose.group(1)):
                issues.append(f"{label}：缺少中文作用说明")
            if isinstance(node, ast.ClassDef):
                classes += 1
                if "类说明（" not in block:
                    issues.append(f"{label}：缺少类说明")
                is_sql = (
                    node.name.startswith("SqlAlchemy")
                    or node.name
                    in {
                        "SqlBehaviorOutbox",
                        "SqliteBm25Repository",
                        "SqliteCheckpointSaver",
                        "Base",
                    }
                    or "/db/models/" in path.as_posix()
                )
                if is_sql:
                    sql_classes += 1
                    if "SQL 类" not in block:
                        issues.append(f"{label}：缺少 SQL 类标识")
                declarations = [
                    statement
                    for statement in node.body
                    if isinstance(statement, (ast.Assign, ast.AnnAssign))
                ]
                for method in node.body:
                    if (
                        isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and method.name == "__init__"
                    ):
                        declarations.extend(
                            statement
                            for statement in ast.walk(method)
                            if isinstance(statement, (ast.Assign, ast.AnnAssign))
                        )
                for declaration in declarations:
                    targets = (
                        declaration.targets
                        if isinstance(declaration, ast.Assign)
                        else [declaration.target]
                    )
                    names = (
                        [
                            target.id
                            for target in targets
                            if isinstance(target, ast.Name)
                        ]
                        if declaration in node.body
                        else []
                    )
                    attributes = [
                        target.attr
                        for target in targets
                        if isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ]
                    if not names and not attributes:
                        continue
                    field_block = comment_block(lines, declaration)
                    for name in names + attributes:
                        marker = "字段说明：" if name in names else "实例属性说明："
                        if marker + name not in field_block or not re.search(
                            r"# 作用：[^\n]*[\u4e00-\u9fff]", field_block
                        ):
                            issues.append(f"{label}：缺少字段 {name} 的中文作用说明")
                    fields += len(names)
                    instance_attributes += len(attributes)
                    annotation = getattr(declaration, "annotation", None)
                    choices = literal_members(annotation)
                    if annotation is not None:
                        for component in ast.walk(annotation):
                            if isinstance(component, ast.Name):
                                choices.extend(aliases.get(component.id, []))
                    if (
                        any(ast.unparse(base).endswith("Enum") for base in node.bases)
                        and isinstance(declaration.value, ast.Constant)
                        and isinstance(declaration.value.value, str)
                    ):
                        choices.append(declaration.value.value)
                    for choice in dict.fromkeys(choices):
                        literal_values += 1
                        if not re.search(
                            r"#\s+" + re.escape(choice) + r"：[^\n]*[\u4e00-\u9fff]",
                            field_block,
                        ):
                            issues.append(f"{label}：缺少取值 {choice} 的中文含义说明")
                continue
            methods += 1
            if (
                "方法说明：" not in block
                or "入参：" not in block
                or "出参：" not in block
            ):
                issues.append(f"{label}：方法说明、入参或出参不完整")
            arguments = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            arguments += [
                arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None
            ]
            for argument in arguments:
                if argument.arg in {"self", "cls"}:
                    continue
                if not re.search(rf"(?<!\w){re.escape(argument.arg)}（", block):
                    issues.append(f"{label}：缺少参数 {argument.arg} 的说明")
    return {
        "files": len(files),
        "classes": classes,
        "methods_and_functions": methods,
        "sql_classes": sql_classes,
        "fields": fields,
        "instance_attributes": instance_attributes,
        "documented_choices": literal_values,
        "issues": issues,
    }


def main() -> int:
    """执行注释完整性检查并打印结果。

    入参：无；项目根目录由本脚本位置确定。
    出参：无缺漏时为 0，存在缺漏时为 1。
    """
    result = audit(Path(__file__).resolve().parents[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
