"""Static trusted-source closure check for Context projection release tests.

It is deliberately conservative and finite: it rejects undeclared local helper
imports and direct file I/O in checked modules. Adapters are explicit, named,
and require a reason; this is not a runtime sandbox or dynamic-import proof.
"""

import ast
from pathlib import Path

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
ENTRIES = {
    "context.integrity",
    "context.source",
    "context.read_scope",
    "quality_gate",
    "evidence_validator",
    "decision",
    "interface_contract",
    "diagnosability",
    "risk_boundaries",
}
ALLOWED = ENTRIES | {
    "context.builder",
    "context.escalation",
    "context.freshness",
    "context.store",
    "context.evidence",
    "context.model",
    "context.policy",
    "context.selector",
    "blockers",
    "paths",
    "state_machine",
    "test_plan",
    "workspace",
    "repository",
    "schema_resources",
    "source_access",
    "git_query",
    "transaction",
    "evidence_validator",
    "decision",
    "interface_contract",
    "diagnosability",
    "risk_boundaries",
    "risk",
    "init",
    "templates",
    "collect_evidence",
    "existing_verification",
    "telemetry_lock",
}
ADAPTERS = {
    "source_access": "audited source access",
    "workspace": "fixed Git query adapter",
    "git_query": "fixed Git subprocess adapter",
    "schema_resources": "registered package resources",
    "transaction": "publication writes",
    "telemetry_lock": "process lock adapter",
    "context.escalation": "projection uses pure policy readers; expansion publication is outside read scope",
    "context.freshness": "bootstrap manifest construction; two-phase source guard tracked by SRC-09 audit",
    "repository": "repository root discovery adapter",
    "test_plan": "test plan validator dependency boundary",
    "collect_evidence": "evidence collection dependency boundary",
    "context.store": "derived snapshot publication boundary",
}


def _module_path(root: Path, name: str) -> Path | None:
    candidate = root / (name.replace(".", "/") + ".py")
    return candidate if candidate.is_file() else None


def _imports(tree: ast.AST, module: str) -> set[str]:
    result = set()
    package = module.split(".")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1] + (
                    node.module or ""
                ).split(".")
                if base and base != [""]:
                    result.add(".".join(part for part in base if part))
            elif node.module and node.module.startswith("harness"):
                result.add(node.module.removeprefix("harness."))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("harness."):
                    result.add(alias.name.removeprefix("harness."))
    return result


def _direct_io_lines(tree: ast.AST) -> list[int]:
    source_access_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "harness"
        for alias in node.names
        if alias.name == "source_access"
    }
    return sorted(
        {
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in FORBIDDEN
            and not (
                isinstance(node.value, ast.Name)
                and node.value.id in source_access_names
            )
        }
    )


def assert_trusted_closure(
    root: Path,
    *,
    entries: set[str] | None = None,
    allowed: set[str] | None = None,
    adapters: dict[str, str] | None = None,
) -> None:
    entries = ENTRIES if entries is None else entries
    allowed = ALLOWED if allowed is None else allowed
    adapters = ADAPTERS if adapters is None else adapters
    for name, reason in adapters.items():
        if not isinstance(reason, str) or not reason.strip():
            raise AssertionError(f"ADAPTER_REASON_REQUIRED: {name}")
    pending, seen = set(entries), set()
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _module_path(root, module)
        if path is None:
            continue
        tree = ast.parse(path.read_text())
        if module in adapters:
            continue
        for dependency in _imports(tree, module):
            if _module_path(root, dependency) is None:
                continue
            if dependency not in allowed and dependency not in adapters:
                raise AssertionError(
                    f"DEPENDENCY_CLOSURE_UNDECLARED: {module} -> {dependency}"
                )
            pending.add(dependency)
        if module not in adapters:
            lines = _direct_io_lines(tree)
            if lines:
                raise AssertionError(f"DIRECT_IO: {module}:{lines}")
