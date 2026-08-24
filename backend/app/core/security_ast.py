from typing import Any
import ast

FORBIDDEN_MODULES = {
    "os",
    "sys",
    "subprocess",
    "shutil",
    "importlib",
    "socket",
    "signal",
    "multiprocessing",
    "pathlib",
    "glob",
    "tempfile",
    "platform",
}

FORBIDDEN_FUNCTIONS = {"eval", "exec", "open"}


class SecurityVisitor(ast.NodeVisitor):
    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            if alias.name in FORBIDDEN_MODULES:
                raise ValueError(f"Forbidden module import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        if node.module in FORBIDDEN_MODULES:
            raise ValueError(f"Forbidden module import: {node.module}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        # Case 1: simple function name
        if isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_FUNCTIONS:
                raise ValueError(f"Forbidden function call: {node.func.id}")

        # Case 2: attribute call (like math.sqrt)
        elif isinstance(node.func, ast.Attribute):
            full_name = (
                f"{node.func.value.id}.{node.func.attr}"
                if isinstance(node.func.value, ast.Name)
                else node.func.attr
            )
            if full_name in FORBIDDEN_FUNCTIONS:
                raise ValueError(f"Forbidden function call: {full_name}")

        self.generic_visit(node)


def validate_code(code: str) -> None:
    """Parse and validate python code string using SecurityVisitor."""
    tree = ast.parse(code)
    visitor = SecurityVisitor()
    visitor.visit(tree)
