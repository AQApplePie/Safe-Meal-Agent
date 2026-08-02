"""Executable dependency rules for the modular monolith."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "safemeal"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _python_files(path: Path) -> list[Path]:
    return sorted(item for item in path.rglob("*.py") if "migrations" not in item.parts)


def _assert_no_import_roots(paths: list[Path], forbidden: set[str]) -> None:
    violations: list[str] = []
    for path in paths:
        for imported in _imports(path):
            root = imported.split(".", 1)[0]
            if root in forbidden:
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert not violations, "forbidden imports:\n" + "\n".join(violations)


def _component_for_path(path: Path) -> str:
    parts = path.relative_to(PACKAGE).parts
    if parts[0] == "modules" and len(parts) > 1:
        return f"modules.{parts[1]}"
    return parts[0].removesuffix(".py")


def _component_for_import(imported: str) -> str | None:
    parts = imported.split(".")
    if len(parts) < 2 or parts[0] != "safemeal":
        return None
    if parts[1] == "modules" and len(parts) > 2:
        return f"modules.{parts[2]}"
    return parts[1]


def test_domain_has_no_framework_or_infrastructure_dependencies() -> None:
    domain_files = list((PACKAGE / "application" / "domain").glob("*.py"))
    domain_files.extend(PACKAGE.glob("modules/**/domain.py"))
    _assert_no_import_roots(
        domain_files,
        {
            "fastapi",
            "langgraph",
            "sqlalchemy",
            "redis",
            "pymilvus",
            "neo4j",
        },
    )
    for path in domain_files:
        assert not any(
            imported.startswith("safemeal.infrastructure")
            for imported in _imports(path)
        ), path


def test_application_does_not_depend_on_infrastructure_implementations() -> None:
    violations = [
        f"{path.relative_to(ROOT)} -> {imported}"
        for path in _python_files(PACKAGE / "application")
        for imported in _imports(path)
        if imported.startswith("safemeal.infrastructure")
    ]
    assert not violations, "reverse dependencies:\n" + "\n".join(violations)


def test_http_endpoints_do_not_import_database_or_retrieval_sdks() -> None:
    _assert_no_import_roots(
        _python_files(PACKAGE / "interfaces" / "http" / "v1" / "endpoints"),
        {"sqlalchemy", "redis", "pymilvus", "neo4j"},
    )


def test_langgraph_nodes_do_not_construct_infrastructure_clients() -> None:
    node_files = _python_files(PACKAGE / "application" / "agents" / "nodes")
    violations = [
        f"{path.relative_to(ROOT)} -> {imported}"
        for path in node_files
        for imported in _imports(path)
        if imported.startswith("safemeal.infrastructure")
    ]
    assert not violations, "node infrastructure dependencies:\n" + "\n".join(violations)


def test_architecture_components_have_no_import_cycles() -> None:
    graph: dict[str, set[str]] = {}
    for path in _python_files(PACKAGE):
        source = _component_for_path(path)
        graph.setdefault(source, set())
        for imported in _imports(path):
            target = _component_for_import(imported)
            if target is not None and target != source:
                graph[source].add(target)

    visiting: list[str] = []
    visited: set[str] = set()

    def visit(component: str) -> None:
        if component in visiting:
            start = visiting.index(component)
            cycle = [*visiting[start:], component]
            raise AssertionError("import cycle: " + " -> ".join(cycle))
        if component in visited:
            return
        visiting.append(component)
        for dependency in sorted(graph.get(component, ())):
            visit(dependency)
        visiting.pop()
        visited.add(component)

    for component in sorted(graph):
        visit(component)


def test_legacy_backend_and_generic_plugin_platform_are_removed() -> None:
    assert not (ROOT / "back").exists()
    plugin_sources = list((PACKAGE / "plugins").glob("**/*.py"))
    assert not plugin_sources
