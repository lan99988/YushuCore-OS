from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


_AGENT_BEHAVIOR_MODULES = (
    "_shared.py",
    "body.py",
    "domain_analyzer.py",
    "domain_reviewer.py",
    "knowledge.py",
    "knowledge_analyzer.py",
    "knowledge_reviewer.py",
    "project.py",
    "sdk.py",
    "skills.py",
    "study.py",
)

_FORBIDDEN_IMPORT_ROOTS = {"os", "pathlib", "shutil"}
_FORBIDDEN_NAME_CALLS = {"open", "Path"}
_FORBIDDEN_METHOD_CALLS = {
    "open",
    "read_text",
    "write_text",
    "read_bytes",
    "write_bytes",
    "unlink",
    "rename",
    "replace",
    "mkdir",
    "rmdir",
}
_FORBIDDEN_MODULE_CALLS = {
    ("os", "remove"),
    ("os", "unlink"),
    ("os", "rmdir"),
    ("os", "removedirs"),
    ("os", "rename"),
    ("os", "replace"),
    ("shutil", "rmtree"),
    ("shutil", "move"),
    ("shutil", "copy"),
    ("shutil", "copy2"),
}
_FORBIDDEN_VAULT_STRINGS = (
    "D:\\Personal_Knowledge_Vault",
    "D:/Personal_Knowledge_Vault",
    "Personal_Knowledge_Vault",
)


@dataclass(frozen=True)
class BoundaryViolation:
    module: str
    line: int
    rule: str
    detail: str


@dataclass(frozen=True)
class AgentBoundaryReport:
    scanned_modules: tuple[str, ...]
    violations: tuple[BoundaryViolation, ...]

    @property
    def violation_count(self) -> int:
        return len(self.violations)

    def is_clean(self) -> bool:
        return not self.violations


class _BoundaryVisitor(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.violations: list[BoundaryViolation] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root_name = alias.name.split(".", maxsplit=1)[0]
            if root_name in _FORBIDDEN_IMPORT_ROOTS:
                self._add(node, "forbidden_import", f"Agent behavior modules must not import {root_name}.")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        root_name = module.split(".", maxsplit=1)[0]
        if root_name in _FORBIDDEN_IMPORT_ROOTS:
            self._add(node, "forbidden_import", f"Agent behavior modules must not import from {root_name}.")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_NAME_CALLS:
            self._add(node, "forbidden_call", f"Direct {node.func.id}() calls bypass Runtime/Gateway boundaries.")

        if isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if attr_name in _FORBIDDEN_METHOD_CALLS:
                self._add(node, "forbidden_method", f"Direct .{attr_name}() calls bypass Runtime/Gateway boundaries.")
            if isinstance(node.func.value, ast.Name):
                module_call = (node.func.value.id, attr_name)
                if module_call in _FORBIDDEN_MODULE_CALLS:
                    self._add(
                        node,
                        "forbidden_module_call",
                        f"Direct {module_call[0]}.{module_call[1]}() calls bypass Runtime/Gateway boundaries.",
                    )

        self.generic_visit(node)

    def _add(self, node: ast.AST, rule: str, detail: str) -> None:
        self.violations.append(
            BoundaryViolation(
                module=self.module,
                line=getattr(node, "lineno", 0),
                rule=rule,
                detail=detail,
            )
        )


def phase3_agent_boundary_report(agents_dir: str | Path | None = None) -> AgentBoundaryReport:
    root = Path(agents_dir) if agents_dir is not None else Path(__file__).parent
    scanned: list[str] = []
    violations: list[BoundaryViolation] = []

    for module_name in _AGENT_BEHAVIOR_MODULES:
        module_path = root / module_name
        if not module_path.exists():
            continue
        scanned.append(module_name)
        source = module_path.read_text(encoding="utf-8")
        violations.extend(_scan_for_vault_strings(module_name, source))
        violations.extend(_scan_python_module(module_name, source))

    return AgentBoundaryReport(scanned_modules=tuple(scanned), violations=tuple(violations))


def _scan_for_vault_strings(module_name: str, source: str) -> tuple[BoundaryViolation, ...]:
    violations: list[BoundaryViolation] = []
    lines = source.splitlines()
    for line_number, line in enumerate(lines, start=1):
        for forbidden in _FORBIDDEN_VAULT_STRINGS:
            if forbidden in line:
                violations.append(
                    BoundaryViolation(
                        module=module_name,
                        line=line_number,
                        rule="forbidden_vault_path",
                        detail="Agent behavior modules must not hard-code the Knowledge Vault path.",
                    )
                )
    return tuple(violations)


def _scan_python_module(module_name: str, source: str) -> tuple[BoundaryViolation, ...]:
    tree = ast.parse(source, filename=module_name)
    visitor = _BoundaryVisitor(module_name)
    visitor.visit(tree)
    return tuple(visitor.violations)
