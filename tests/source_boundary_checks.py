"""Conservative lint for migrated trusted modules, not arbitrary Python analysis.

Reject I/O references as well as calls so simple aliases cannot hide reads.
Dynamic reflection and transitive helper imports still require closure review.
"""

import ast

FORBIDDEN = {
    "open",
    "read_text",
    "read_bytes",
    "exists",
    "is_file",
    "is_dir",
    "is_symlink",
    "stat",
    "lstat",
    "glob",
    "rglob",
    "scandir",
    "listdir",
}


def direct_io_lines(source: str) -> list[int]:
    tree = ast.parse(source)
    nodes = list(ast.walk(tree))
    modules = set()
    functions = set()
    imports = {}
    violations = set()
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname or alias.name
                imports[name] = imports.get(name, 0) + 1
                if node.module == "harness" and alias.name == "source_access":
                    modules.add(name)
                elif node.module == "harness.source_access":
                    functions.add(name)
                elif alias.name in FORBIDDEN or alias.name == "*":
                    violations.add(node.lineno)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imports[name] = imports.get(name, 0) + 1
                if alias.name == "harness.source_access" and alias.asname:
                    modules.add(name)
    rebound = {
        node.id
        for node in nodes
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
    }
    rebound.update(node.arg for node in nodes if isinstance(node, ast.arg))
    rebound.update(
        node.name for node in nodes if isinstance(node, ast.ExceptHandler) and node.name
    )
    rebound.update(
        node.name
        for node in nodes
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )
    rebound.update(name for name, count in imports.items() if count > 1)
    modules -= rebound
    functions -= rebound
    for node in nodes:
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN:
            if not (isinstance(node.value, ast.Name) and node.value.id in modules):
                violations.add(node.lineno)
        elif (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id == "open"
            and node.id not in functions
        ):
            violations.add(node.lineno)
    return sorted(violations)
