"""约束物理架构的依赖方向，防止后续功能重新耦合模块。"""

import ast
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "safemeal"
AGENT = PACKAGE / "agent"
MODULES = PACKAGE / "modules"
BOOTSTRAP = PACKAGE / "bootstrap"


def imports(path: Path):
    """返回文件中的绝对导入模块名。"""
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            yield node.module or ""
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def test_infrastructure_only_imported_from_infrastructure_or_bootstrap():
    """具体技术实现只能由基础设施内部或装配根引用。"""
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE).parts
        if relative[0] in {"infrastructure", "bootstrap"} or relative == ("main.py",):
            continue
        assert not any(
            module.startswith("safemeal.infrastructure") for module in imports(path)
        ), str(path)


def test_business_modules_do_not_depend_on_agent():
    """业务事实不能反向依赖智能体决策层。"""
    violations = [
        (str(path), module)
        for path in MODULES.rglob("*.py")
        for module in imports(path)
        if module.startswith("safemeal.agent")
    ]
    assert violations == []


def test_business_modules_do_not_import_framework_or_composition():
    """业务模块不得依赖 LangGraph、装配根或运行时配置。"""
    forbidden = ("langgraph", "safemeal.bootstrap", "safemeal.config")
    for path in MODULES.rglob("*.py"):
        assert not any(module.startswith(forbidden) for module in imports(path)), str(path)


def test_outer_and_inner_graphs_remain_distinct():
    """外层控制流与内层决策循环必须保留各自的装配入口。"""
    assert (AGENT / "workflow" / "graph.py").is_file()
    assert (AGENT / "runtime" / "orchestration" / "graph.py").is_file()
    imported = set(imports(BOOTSTRAP / "composition" / "application_container.py"))
    assert "safemeal.agent.runtime.orchestration" in imported
    assert "safemeal.agent.workflow.graph" in imported


def test_nodes_are_not_declared_inside_graph_wiring():
    """Graph 文件只负责装配，不重新内嵌节点实现。"""
    graph_paths = (
        AGENT / "workflow" / "graph.py",
        AGENT / "runtime" / "orchestration" / "graph.py",
    )
    for graph_path in graph_paths:
        tree = ast.parse(graph_path.read_text())
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name.startswith("build_")
                assert not any(
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    for child in ast.walk(node)
                    if child is not node
                )


def test_tools_are_adapters_without_infrastructure_dependencies():
    """Tool 只适配应用服务，不能直接拥有技术实现。"""
    adapters = AGENT / "runtime" / "tools" / "adapters"
    for path in adapters.glob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.ClassDef):
                assert node.name.endswith("Tool"), (str(path), node.name)
        assert not any(
            module.startswith(("safemeal.infrastructure", "safemeal.config"))
            for module in imports(path)
        ), str(path)


def test_core_systems_import_without_database_or_model_configuration():
    """导入两个 Graph 不应隐式初始化数据库或配置。"""
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    code = (
        "from safemeal.agent.runtime.orchestration import build_agent_graph; "
        "from safemeal.agent.workflow.graph import build_chat_workflow; "
        "import sys; assert 'safemeal.config.settings' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_legacy_application_implementations_are_removed():
    """旧 application 目录不能继续承载第二套真实实现。"""
    application = PACKAGE / "application"
    remaining = (
        [path for path in application.rglob("*.py") if path.name != "__init__.py"]
        if application.exists()
        else []
    )
    assert remaining == []


def test_agent_exposes_physical_boundaries():
    """Agent 的理解、上下文、外层流程与内层运行时均为真实目录。"""
    expected = {"contracts", "understanding", "context", "workflow", "runtime", "gateway"}
    assert expected <= {path.name for path in AGENT.iterdir() if path.is_dir()}
    for layer in expected:
        assert (AGENT / layer / "__init__.py").is_file()
    runtime_layers = {"orchestration", "model", "tools", "memory", "aggregation"}
    runtime = AGENT / "runtime"
    assert runtime_layers <= {path.name for path in runtime.iterdir() if path.is_dir()}


def test_production_composition_uses_public_agent_layers():
    """生产装配通过公开边界连接 Agent，不依赖遗留路径。"""
    imported = set(imports(BOOTSTRAP / "composition" / "application_container.py"))
    assert "safemeal.agent.gateway" in imported
    assert "safemeal.agent.runtime.orchestration" in imported
    assert "safemeal.agent.runtime.tools" in imported
    assert not any(module.startswith("safemeal.application") for module in imported)


def test_production_tools_publish_complete_usage_boundaries():
    """每个生产 Tool 都必须声明用途、使用与禁用边界。"""
    from safemeal.agent.runtime.tools.adapters.constraint_verification import VerifyRecipeConstraintsTool
    from safemeal.agent.runtime.tools.adapters.dietary_search import DietarySafeRecipeQueryTool
    from safemeal.agent.runtime.tools.adapters.knowledge_search import KnowledgeSearchTool
    from safemeal.agent.runtime.tools.adapters.recipe_tools import (
        GenerateRecipeTool,
        GetRecipeTool,
        RecommendRecipesTool,
        SearchRecipesTool,
    )

    tool_types = (
        SearchRecipesTool,
        GetRecipeTool,
        RecommendRecipesTool,
        GenerateRecipeTool,
        DietarySafeRecipeQueryTool,
        KnowledgeSearchTool,
        VerifyRecipeConstraintsTool,
    )
    for tool_type in tool_types:
        assert tool_type.purpose
        assert tool_type.use_when
        assert tool_type.do_not_use_when
        assert tool_type.input_constraints
