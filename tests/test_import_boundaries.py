"""
Import Boundaries Architectural Guardrail Tests.
Enforces strict unidirectional dependencies across Hexagonal architecture layers using AST inspection.
Detects static imports, from-imports, and dynamic import invocations.
"""
import ast
from pathlib import Path
from typing import Dict, List, Set
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent

FORBIDDEN_IMPORTS_MAP: Dict[str, Set[str]] = {
    # Core must be completely pure domain & ports
    "packages/fleet-governance-core": {
        "fastapi",
        "requests",
        "google",
        "google.cloud",
        "fleet_adapter_pdx",
        "fleet_adapter_prodocux",
        "fleet_adapter_gcp",
        "fleet_adapter_google_adk",
        "fleet_domain_cosmetics",
        "fleet_api",
    },
    # Domain must only import Core
    "packages/fleet-domain-cosmetics": {
        "fastapi",
        "requests",
        "google",
        "google.cloud",
        "fleet_adapter_pdx",
        "fleet_adapter_prodocux",
        "fleet_adapter_gcp",
        "fleet_adapter_google_adk",
        "fleet_api",
    },
    # Adapters must not import other parallel adapters or API layer
    "packages/fleet-adapter-pdx": {
        "fastapi",
        "fleet_adapter_gcp",
        "fleet_adapter_prodocux",
        "fleet_adapter_google_adk",
        "fleet_api",
    },
    "packages/fleet-adapter-prodocux": {
        "fastapi",
        "fleet_adapter_gcp",
        "fleet_adapter_pdx",
        "fleet_adapter_google_adk",
        "fleet_api",
    },
    "packages/fleet-adapter-gcp": {
        "fastapi",
        "fleet_adapter_pdx",
        "fleet_adapter_prodocux",
        "fleet_adapter_google_adk",
        "fleet_api",
    },
    "packages/fleet-adapter-google-adk": {
        "fastapi",
        "fleet_adapter_pdx",
        "fleet_adapter_prodocux",
        "fleet_adapter_gcp",
        "fleet_api",
    },
}

def extract_module_imports(py_file_path: Path) -> Set[str]:
    """Parse a python file AST and return all static and dynamic imported module names."""
    try:
        content = py_file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file_path))
    except Exception as e:
        pytest.fail(f"Failed to parse AST for {py_file_path}: {e}")

    imported = set()
    for node in ast.walk(tree):
        # 1. Standard import foo
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        # 2. From foo import bar
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
        # 3. Dynamic import: __import__('foo') or importlib.import_module('foo')
        elif isinstance(node, ast.Call):
            func = node.func
            target_arg = None
            if isinstance(func, ast.Name) and func.id == "__import__" and node.args:
                target_arg = node.args[0]
            elif isinstance(func, ast.Attribute) and func.attr == "import_module" and node.args:
                target_arg = node.args[0]

            if target_arg and isinstance(target_arg, ast.Constant) and isinstance(target_arg.value, str):
                imported.add(target_arg.value.split(".")[0])

    return imported

@pytest.mark.parametrize("package_rel_path,forbidden_set", FORBIDDEN_IMPORTS_MAP.items())
def test_package_import_boundaries(package_rel_path: str, forbidden_set: Set[str]):
    pkg_dir = ROOT_DIR / package_rel_path / "src"
    if not pkg_dir.exists():
        pytest.skip(f"Directory {pkg_dir} does not exist")

    violations: List[str] = []
    for py_file in pkg_dir.rglob("*.py"):
        imported_modules = extract_module_imports(py_file)
        illegal = imported_modules.intersection(forbidden_set)
        if illegal:
            violations.append(f"{py_file.relative_to(ROOT_DIR)} illegally imports {illegal}")

    assert not violations, f"Architectural boundary violations found:\n" + "\n".join(violations)
