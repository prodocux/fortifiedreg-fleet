"""
AST-Based Import Boundary Guard Test (v0.4.0).
Enforces architectural purity by strictly verifying that Fleet runtime codebase
NEVER imports Office or PDF binary renderers (docx, openpyxl, pptx, reportlab).
"""
import ast
import os
from pathlib import Path
import pytest

BANNED_MODULES = {"docx", "openpyxl", "pptx", "reportlab", "pypdf", "fitz"}

ROOT_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIRS = [
    ROOT_DIR / "packages" / "fleet-governance-core" / "src",
    ROOT_DIR / "packages" / "fleet-domain-cosmetics" / "src",
    ROOT_DIR / "packages" / "fleet-adapter-pdx" / "src",
    ROOT_DIR / "packages" / "fleet-adapter-prodocux" / "src",
    ROOT_DIR / "packages" / "fleet-adapter-google-adk" / "src",
    ROOT_DIR / "packages" / "fleet-adapter-gcp" / "src",
    ROOT_DIR / "packages" / "fleet-adapter-local" / "src",
    ROOT_DIR / "apps" / "fleet-api" / "src",
]


def test_runtime_codebase_has_zero_banned_binary_renderer_imports():
    """Scan all Python ASTs in Fleet runtime to ensure 0 banned renderer imports."""
    violations = []

    for runtime_dir in RUNTIME_DIRS:
        if not runtime_dir.exists():
            continue

        for py_file in runtime_dir.rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            except Exception as e:
                pytest.fail(f"Failed to parse AST for {py_file}: {e}")

            for node in ast.walk(tree):
                # 1. Check `import x, y as z`
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        base_mod = alias.name.split(".")[0]
                        if base_mod in BANNED_MODULES:
                            violations.append(f"{py_file}:{node.lineno} -> import {alias.name}")

                # 2. Check `from x import y`
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        base_mod = node.module.split(".")[0]
                        if base_mod in BANNED_MODULES:
                            violations.append(f"{py_file}:{node.lineno} -> from {node.module} import ...")

                # 3. Check dynamic `__import__("x")`
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == "__import__":
                        if node.args and isinstance(node.args[0], ast.Constant):
                            arg_val = str(node.args[0].value).split(".")[0]
                            if arg_val in BANNED_MODULES:
                                violations.append(f"{py_file}:{node.lineno} -> __import__('{node.args[0].value}')")

    assert len(violations) == 0, f"Architecture Boundary Violation! Banned renderer imports detected in Fleet runtime:\n" + "\n".join(violations)
