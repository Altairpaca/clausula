import ast
from pathlib import Path


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_domain_has_no_outer_layer_imports():
    forbidden = ("clausula.adapters", "clausula.application", "clausula.api", "clausula.agent", "fastapi", "mcp", "typer")
    for path in Path("clausula/domain").rglob("*.py"):
        for imported in imported_modules(path):
            assert not imported.startswith(forbidden), f"{path} imports outer layer {imported}"


def test_application_has_no_transport_or_agent_imports():
    forbidden = ("clausula.api", "clausula.cli", "clausula.agent", "fastapi", "mcp", "typer")
    for path in Path("clausula/application").rglob("*.py"):
        for imported in imported_modules(path):
            assert not imported.startswith(forbidden), f"{path} imports adapter {imported}"
