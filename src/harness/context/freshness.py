"""Version the finite Context/Gate source set separately from product evidence."""

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

import yaml

from harness import source_access
from harness.schema_resources import schema_versions
from harness.source_access import source_scope
from harness.workspace import WorkspaceError, snapshot

from .model import ContextBuildError
from .source import ARTIFACT_PATTERNS

PROJECTION_VERSION = 2
ROOT_FILES = (
    "current-task.yaml",
    "requirements.yaml",
    "invariants.yaml",
    "impact.yaml",
    "gate.yaml",
    "risk-boundaries.yaml",
    "observability.yaml",
    "config.yaml",
    "context/expansions.yaml",
    "decisions/index.yaml",
)
ARTIFACT_DIRS = tuple(ARTIFACT_PATTERNS)


def digest(value) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
    )


def contained_path(root: Path, ref: str) -> Path:
    path = Path(ref)
    if path.is_absolute() or ".." in path.parts or not ref:
        raise ContextBuildError("CONTEXT_REFERENCE_BROKEN", "noncanonical reference")
    candidate = root / path
    try:
        if not candidate.resolve().is_relative_to(root.resolve()):
            raise ContextBuildError(
                "CONTEXT_REFERENCE_BROKEN", f"outside repository: {ref}"
            )
    except (OSError, RuntimeError) as exc:
        raise ContextBuildError(
            "CONTEXT_REFERENCE_BROKEN", "unresolvable reference"
        ) from exc
    return candidate


def file_version(path: Path) -> str | None:
    if path.is_symlink() and not path.exists():
        raise ContextBuildError(
            "CONTEXT_REFERENCE_BROKEN", f"dangling source: {path.name}"
        )
    if not path.exists():
        return None
    if path.is_dir():
        return digest({"directory": path.name})
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _declared_paths(harness_dir: Path) -> set[str]:
    """Explicit paths only: no glob expansion or repository enumeration."""
    result = set()
    for name in ("current-task.yaml", "impact.yaml", "observability.yaml"):
        path = harness_dir / name
        if not path.exists():
            continue
        document = yaml.safe_load(path.read_text())
        if not isinstance(document, dict):
            continue  # canonical loader reports the schema error
        containers = []
        if name == "current-task.yaml":
            containers = [
                (document.get("scope"), ("owned_paths", "protected_user_paths"))
            ]
        elif name == "impact.yaml":
            containers = [
                (
                    document.get("impact"),
                    ("changed", "direct_dependents", "contracts", "required_tests"),
                )
            ]
        else:
            containers = [(document.get("applicability"), ("inspected_paths",))]
        for container, keys in containers:
            if not isinstance(container, dict):
                continue
            for key in keys:
                values = container.get(key, [])
                if isinstance(values, list):
                    result.update(
                        value.split("::", 1)[0]
                        for value in values
                        if isinstance(value, str)
                    )
    for name, key in (
        ("requirements.yaml", "requirements"),
        ("invariants.yaml", "invariants"),
    ):
        path = harness_dir / name
        if not path.exists():
            continue
        document = yaml.safe_load(path.read_text())
        records = document.get(key, []) if isinstance(document, dict) else []
        if not isinstance(records, list):
            continue
        for record in records:
            plan = record.get("test_plan") if isinstance(record, dict) else None
            if not isinstance(plan, dict) or not isinstance(plan.get("cases"), list):
                continue
            for case in plan["cases"]:
                tests = case.get("tests", []) if isinstance(case, dict) else []
                if isinstance(tests, list):
                    result.update(
                        test.split("::", 1)[0]
                        for test in tests
                        if isinstance(test, str)
                    )
    findings = harness_dir / "findings"
    if findings.is_dir():
        for path in sorted(findings.glob("*.yaml")):
            record = yaml.safe_load(path.read_text())
            if not isinstance(record, dict):
                continue
            for section, key in (("regression_test", "path"), ("location", "file")):
                value = record.get(section)
                if isinstance(value, dict) and isinstance(value.get(key), str):
                    result.add(value[key].split("::", 1)[0])
    result.update(_current_task_decision_scope_paths(harness_dir))
    return result


def _current_task_decision_scope_paths(harness_dir: Path) -> set[str]:
    """Declared paths from current-task decision bodies only, never historical YAML."""
    from harness import decision

    task_path = harness_dir / "current-task.yaml"
    if not task_path.exists():
        return set()
    document = yaml.safe_load(task_path.read_text())
    task_id = (document or {}).get("task", {}).get("id") if isinstance(document, dict) else None
    if not task_id:
        return set()
    try:
        index = decision.load_decision_index(harness_dir)
    except decision.DecisionError:
        return set()
    declared: set[str] = set()
    for meta in index:
        if meta.get("task_id") != task_id:
            continue
        try:
            record = decision.load_decision(harness_dir, meta["id"])
        except decision.DecisionError:
            continue
        scope = record.get("scope", [])
        if isinstance(scope, list):
            declared.update(name for name in scope if isinstance(name, str))
    return declared


def _protected_paths(harness_dir: Path) -> set[str]:
    """FAST reads these as literal filenames, not scope globs/test selectors."""
    path = harness_dir / "current-task.yaml"
    if not source_access.exists(path):
        return set()  # canonical loader reports missing/invalid task data
    value = yaml.safe_load(source_access.read_text(path))
    for field in ("risk", "user_changes", "paths"):
        value = value.get(field) if isinstance(value, dict) else None
    if not isinstance(value, list):
        return set()
    return {name for name in value if isinstance(name, str)}


@contextmanager
def bootstrap_scope(harness_dir: Path):
    """Discover declarations from finite canonical roots before later reads.

    This scope deliberately excludes arbitrary adjacent control files. Artifact
    member rules authorize only canonical immediate members used by discovery.
    """
    root = harness_dir.absolute().parent
    allowed = [harness_dir / name for name in ROOT_FILES]
    allowed.extend(harness_dir / directory for directory in ARTIFACT_DIRS)
    rules = [
        (harness_dir / directory, "*.yaml") for directory in ("decisions", "findings")
    ]
    with source_scope(root, allowed=allowed, member_rules=rules) as observed:
        yield observed


@contextmanager
def version_scope(harness_dir: Path, discovered: set[str], protected: set[str]):
    """Freeze known control members before bytes/version collection."""
    root = harness_dir.absolute().parent
    allowed = [harness_dir / name for name in ROOT_FILES]
    for directory, pattern in ARTIFACT_PATTERNS.items():
        path = harness_dir / directory
        allowed.append(path)
        if path.is_dir():
            allowed.extend(path.glob(pattern))
    for name in discovered:
        if not any(char in name for char in "*?["):
            allowed.append(contained_path(root, name))
    # FAST protected paths are literal filenames, including `*`/`::`.
    allowed.extend(contained_path(root, name) for name in protected)
    with source_scope(root, allowed=allowed) as observed:
        yield observed


def capture(harness_dir: Path) -> dict:
    """No derived outputs, staging, history or telemetry enter control hash.

    This registry covers current Gate's canonical file reads. Changes to Gate's
    input surface must extend ROOT_FILES/ARTIFACT_DIRS and its regression tests.
    Canonical direct artifact members (including raw evidence) bind collection membership.
    """
    root = harness_dir.absolute().parent
    # Discovery cannot use a dynamic declaration to authorize its own input.
    # The second phase below versions discovered paths after containment checks.
    with bootstrap_scope(harness_dir):
        discovered = _declared_paths(harness_dir)
        protected = _protected_paths(harness_dir)
    try:
        with version_scope(harness_dir, discovered, protected):
            return _capture_versions(harness_dir, root, discovered, protected)
    except (OSError, ValueError, yaml.YAMLError, WorkspaceError) as exc:
        if isinstance(exc, ContextBuildError):
            raise
        raise ContextBuildError(
            "INVALID_HARNESS_STATE", "cannot version context sources"
        ) from exc


def _capture_versions(
    harness_dir: Path, root: Path, discovered: set[str], protected: set[str]
) -> dict:
    files = {}
    try:
        for name in ROOT_FILES:
            path = contained_path(root, f"{harness_dir.name}/{name}")
            files[name] = file_version(path)
        for directory in ARTIFACT_DIRS:
            path = contained_path(root, f"{harness_dir.name}/{directory}")
            if path.exists() and not path.is_dir():
                raise ContextBuildError(
                    "CONTEXT_SCHEMA_INVALID", f"not a directory: {directory}"
                )
            files[directory + "/"] = file_version(path)
            if path.exists():
                for member in source_access.members(path, ARTIFACT_PATTERNS[directory]):
                    relative = member.relative_to(harness_dir.absolute()).as_posix()
                    checked = contained_path(root, f"{harness_dir.name}/{relative}")
                    if directory == "decisions":
                        files[relative] = digest({"member": member.name})
                    else:
                        files[relative] = file_version(checked)
        declared = {}
        # Scope globs do not authorize scans. FAST protected paths, however,
        # name literal files even when their filenames contain glob characters.
        declared_paths = {
            name
            for name in _declared_paths(harness_dir)
            if not any(char in name for char in "*?[")
        } | protected
        for name in sorted(declared_paths | discovered):
            declared[name] = file_version(contained_path(root, name))
        current = snapshot(root)
        resource_versions = schema_versions()
    except (OSError, ValueError, yaml.YAMLError, WorkspaceError) as exc:
        if isinstance(exc, ContextBuildError):
            raise
        raise ContextBuildError(
            "INVALID_HARNESS_STATE", "cannot version context sources"
        ) from exc
    return {
        "projection_version": PROJECTION_VERSION,
        "schema_resources": resource_versions,
        "files": files,
        "declared_files": declared,
        "workspace_hash": current.fingerprint,
        "head": current.head,
        "control_plane_hash": digest(files),
        **{
            f"{key}_hash": digest(
                {
                    name: version
                    for name, version in files.items()
                    if name == filename or name.startswith(filename + "/")
                }
            )
            for key, filename in (
                ("task", "current-task.yaml"),
                ("requirements", "requirements.yaml"),
                ("invariants", "invariants.yaml"),
                ("impact", "impact.yaml"),
                ("findings", "findings"),
                ("decisions", "decisions"),
                ("evidence", "evidence"),
            )
        },
    }


def require_fresh(previous: dict, current: dict) -> None:
    if previous != current:
        raise ContextBuildError(
            "CONTEXT_STALE", "authoritative Context sources changed"
        )
