"""Enforce import directions so future features cannot silently recouple systems."""

import ast
from pathlib import Path
import subprocess
import os
import sys

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "safemeal" / "application"


def imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            yield node.module or ""
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def test_infrastructure_only_imported_from_composition():
    for path in (ROOT / "safemeal").rglob("*.py"):
        relative = path.relative_to(ROOT / "safemeal").parts
        if relative[0] == "infrastructure" or relative[:3] == (
            "application",
            "service",
            "composition",
        ):
            continue
        assert not any(
            x.startswith("safemeal.infrastructure") for x in imports(path)
        ), str(path)


def test_agent_and_workflow_have_no_implementation_imports_between_them():
    for owner, forbidden in [("workflow", "agent"), ("agent", "workflow")]:
        for path in (APP / owner).rglob("*.py"):
            assert not any(
                x.startswith(f"safemeal.application.{forbidden}") for x in imports(path)
            ), str(path)


def test_nodes_are_not_declared_inside_graph_wiring():
    for owner in ("agent", "workflow"):
        tree = ast.parse((APP / owner / "graph.py").read_text())
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name.startswith("build_")
                assert not any(
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    for child in ast.walk(node)
                    if child is not node
                )


def test_tools_contain_only_tool_implementations():
    for path in (APP / "tool").glob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.ClassDef):
                assert node.name.endswith("Tool"), (str(path), node.name)
        assert not any(
            x.startswith(
                (
                    "safemeal.infrastructure",
                    "safemeal.config",
                    "safemeal.application.agent",
                    "safemeal.application.workflow",
                )
            )
            for x in imports(path)
        )


def test_core_systems_import_without_database_or_model_configuration():
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    code = 'from safemeal.application.agent.graph import build_agent_graph; from safemeal.application.workflow.graph import build_chat_workflow; import sys; assert "safemeal.config.settings" not in sys.modules'
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_application_data_classes_are_declared_in_contracts():
    for path in APP.rglob("*.py"):
        if "contracts" in path.relative_to(APP).parts:
            continue
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {ast.unparse(base).split(".")[-1] for base in node.bases}
            decorators = [ast.unparse(item) for item in node.decorator_list]
            assert not bases & {"BaseModel", "TypedDict"}, (str(path), node.name)
            # Stateful strategy objects hold dependencies and are not transport contracts.
            if node.name != "ChunkStrategySelector":
                assert not any(x.startswith("dataclass") for x in decorators), (
                    str(path),
                    node.name,
                )


def test_business_code_does_not_import_composition_or_runtime_settings():
    for path in APP.rglob("*.py"):
        if path.relative_to(APP).parts[:2] == ("service", "composition"):
            continue
        assert not any(
            module.startswith(
                ("safemeal.application.service.composition", "safemeal.config")
            )
            for module in imports(path)
        ), str(path)


def test_service_layout_has_no_legacy_imports_or_eager_factories():
    assert not (APP / "use_cases").exists()
    assert {path.name for path in (APP / "service").glob("*.py")} == {"__init__.py"}
    for path in (ROOT / "safemeal").rglob("*.py"):
        assert not any(
            module.startswith("safemeal.application.use_cases")
            for module in imports(path)
        ), str(path)


def test_contracts_are_grouped_without_eager_graph_dependencies():
    assert {path.name for path in (APP / "contracts").glob("*.py")} == {"__init__.py"}
    code = "from safemeal.application.contracts.memory.models import UserMemoryRead; import sys; assert 'langgraph.graph' not in sys.modules; assert 'safemeal.config.settings' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_legacy_modules_removed_and_contracts_do_not_depend_on_services():
    assert not (ROOT / "safemeal" / "modules").exists()
    for path in (ROOT / "safemeal").rglob("*.py"):
        assert not any(
            module.startswith("safemeal.modules") for module in imports(path)
        ), str(path)


def test_agent_exposes_all_six_architecture_layers():
    """Keep the learning architecture visible as real importable boundaries."""

    agent_root = APP / "agent"
    expected = {
        "gateway",
        "orchestration",
        "model",
        "tools",
        "memory",
        "aggregation",
    }
    assert expected <= {path.name for path in agent_root.iterdir() if path.is_dir()}
    for layer in expected:
        assert (agent_root / layer / "__init__.py").is_file()


def test_production_composition_uses_agent_layer_facades():
    """Prevent new production wiring from bypassing the six public layers."""

    container = APP / "service" / "composition" / "application_container.py"
    imported = set(imports(container))
    assert "safemeal.application.agent.gateway" in imported
    assert "safemeal.application.agent.orchestration" in imported
    assert "safemeal.application.agent.tools" in imported
    assert "safemeal.application.agent.execution_service" not in imported
    assert "safemeal.application.agent.tool_registry" not in imported
    assert "safemeal.application.agent.tool_runtime" not in imported


def test_production_tools_publish_complete_usage_boundaries():
    """Every real Tool must explain purpose, positive use and negative use."""

    from safemeal.application.tool.dietary_search import DietarySafeRecipeQueryTool
    from safemeal.application.tool.recipe_tools import (
        GenerateRecipeTool,
        GetRecipeTool,
        RecommendRecipesTool,
        SearchRecipesTool,
    )
    from safemeal.application.tool.vector_search import VectorSearchTool

    tool_types = (
        SearchRecipesTool,
        GetRecipeTool,
        RecommendRecipesTool,
        GenerateRecipeTool,
        DietarySafeRecipeQueryTool,
        VectorSearchTool,
    )
    for tool_type in tool_types:
        assert tool_type.purpose
        assert tool_type.use_when
        assert tool_type.do_not_use_when
        assert tool_type.input_constraints
    for path in (APP / "contracts").rglob("*.py"):
        assert not any(
            module.startswith(
                ("safemeal.application.service", "safemeal.infrastructure")
            )
            for module in imports(path)
        ), str(path)
