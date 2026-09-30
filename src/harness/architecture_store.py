"""Architecture artifact loading, publication, and read-only workspace projection."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import yaml

from harness import source_access, transaction, workspace
from harness.architecture import (
    ArchitectureError,
    ArchitectureModel,
    architecture_fingerprint,
    load_architecture_document,
    ownership_match_score,
    resolve_ownership,
)
from harness.telemetry_lock import telemetry_lock

_ARCHITECTURE_ARTIFACT = "architecture.yaml"
_TASK_ARTIFACT = "current-task.yaml"


def _load_yaml_bytes(content: bytes) -> object:
    try:
        return yaml.safe_load(content.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ArchitectureError(
            "ARCHITECTURE_SCHEMA_INVALID", "artifact is not valid UTF-8 YAML"
        ) from exc


def _load_task(harness_dir: Path) -> tuple[dict, bytes]:
    content = source_access.read_bytes(harness_dir / _TASK_ARTIFACT)
    try:
        document = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ArchitectureError("ARCHITECTURE_TASK_INVALID", "task is malformed") from exc
    if not isinstance(document, dict):
        raise ArchitectureError("ARCHITECTURE_TASK_INVALID", "task must be a mapping")
    return document, content


def _require_specifying(task: dict) -> None:
    state = task.get("state")
    if state == "IMPLEMENTING":
        raise ArchitectureError("ARCHITECTURE_REALIGNMENT_REQUIRED")
    if state != "SPECIFYING":
        raise ArchitectureError("ARCHITECTURE_MUTATION_STATE_INVALID")


def load_architecture(
    harness_dir: Path, *, required: bool
) -> ArchitectureModel | None:
    """Load canonical Architecture through audited source access."""
    path = harness_dir / _ARCHITECTURE_ARTIFACT
    if not source_access.is_file(path):
        if required:
            raise ArchitectureError("ARCHITECTURE_REQUIRED")
        return None
    content = source_access.read_bytes(path)
    return load_architecture_document(
        _load_yaml_bytes(content), source_size_bytes=len(content)
    )


def _validate_publication(model: ArchitectureModel, repo_root: Path) -> tuple[str, ...]:
    paths = workspace.architecture_path_index(repo_root)
    path_set = set(paths)
    for module in model.modules:
        for evidence in module.evidence:
            if evidence.path not in path_set:
                raise ArchitectureError(
                    "ARCHITECTURE_EVIDENCE_INVALID", evidence.path
                )
    for rule in model.ownership:
        if not rule.allow_empty and not any(
            ownership_match_score(rule, path) is not None for path in paths
        ):
            raise ArchitectureError("ARCHITECTURE_OWNERSHIP_EMPTY", rule.id)
    for path in paths:
        by_score: dict[tuple[int, int, int], list[str]] = {}
        for rule in model.ownership:
            score = ownership_match_score(rule, path)
            if score is not None:
                by_score.setdefault(score, []).append(rule.id)
        if any(len(rule_ids) > 1 for rule_ids in by_score.values()):
            raise ArchitectureError("ARCHITECTURE_OWNERSHIP_AMBIGUOUS", path)
    return paths


def publish_architecture(harness_dir: Path, candidate: Path) -> bool:
    """Validate and atomically publish operator-authored canonical YAML."""
    content = source_access.read_bytes(candidate)
    model = load_architecture_document(
        _load_yaml_bytes(content), source_size_bytes=len(content)
    )
    with telemetry_lock(harness_dir):
        task, _ = _load_task(harness_dir)
        _require_specifying(task)
        _validate_publication(model, harness_dir.parent)
        try:
            existing = load_architecture(harness_dir, required=False)
        except ArchitectureError:
            existing = None  # Valid publication is the repair path for a malformed draft.
        if (
            existing is not None
            and architecture_fingerprint(existing) == architecture_fingerprint(model)
        ):
            return False
        staged = transaction.stage(
            harness_dir,
            [transaction.StagedArtifact(_ARCHITECTURE_ARTIFACT, content)],
        )
        transaction.publish(
            harness_dir,
            staged,
            replace_paths=frozenset({_ARCHITECTURE_ARTIFACT}),
        )
    return True


def mutate_architecture_scope(
    harness_dir: Path, action: str, module_id: str
) -> bool:
    """Add or remove one explicitly declared module under mutation authority."""
    if action not in {"add", "remove"}:
        raise ArchitectureError("ARCHITECTURE_SCOPE_MUTATION_INVALID")
    with telemetry_lock(harness_dir):
        task, original = _load_task(harness_dir)
        _require_specifying(task)
        model = load_architecture(harness_dir, required=True)
        assert model is not None
        known = {module.id for module in model.modules}
        if module_id not in known:
            raise ArchitectureError("ARCHITECTURE_SCOPE_INVALID", module_id)
        scope = task.setdefault("scope", {})
        current = set(scope.get("modules") or ())
        updated = current | {module_id} if action == "add" else current - {module_id}
        if updated == current:
            return False
        scope["modules"] = sorted(updated)
        content = yaml.safe_dump(task, sort_keys=False, allow_unicode=True).encode("utf-8")
        if content == original:
            return False
        staged = transaction.stage(
            harness_dir, [transaction.StagedArtifact(_TASK_ARTIFACT, content)]
        )
        transaction.publish(
            harness_dir,
            staged,
            replace_paths=frozenset({_TASK_ARTIFACT}),
        )
    return True


def validate_architecture(harness_dir: Path) -> dict:
    """Validate canonical model and repository-backed references without writes."""
    model = load_architecture(harness_dir, required=True)
    assert model is not None
    _validate_publication(model, harness_dir.parent)
    return {
        "status": "valid",
        "fingerprint": architecture_fingerprint(model),
        "modules": sorted(module.id for module in model.modules),
        "ownership_rules": len(model.ownership),
    }


def resolve_architecture_path(harness_dir: Path, path: str) -> dict:
    """Resolve one explicit path against canonical Architecture without writes."""
    model = load_architecture(harness_dir, required=True)
    assert model is not None
    return asdict(resolve_ownership(model, path))


def check_architecture(harness_dir: Path) -> dict:
    """Project current task-attributable Git facts against explicit module scope."""
    model = load_architecture(harness_dir, required=True)
    assert model is not None
    task, _ = _load_task(harness_dir)
    try:
        base_commit = task["git"]["base_commit"]
    except (KeyError, TypeError) as exc:
        raise ArchitectureError("ARCHITECTURE_TASK_INVALID", "missing base commit") from exc
    excluded = set((task.get("risk") or {}).get("user_changes", {}).get("paths") or ())
    excluded -= set((task.get("scope") or {}).get("owned_paths") or ())
    changed = tuple(
        record
        for record in workspace.architecture_changes(base_commit, harness_dir.parent)
        if record.path not in excluded
    )
    actual: set[str] = set()
    diagnostics: list[dict] = []
    for path in sorted({record.path for record in changed}):
        resolution = resolve_ownership(model, path)
        if resolution.status == "resolved":
            actual.update(resolution.modules)
        else:
            diagnostics.append(
                {
                    "path": path,
                    "status": resolution.status,
                    "rule_ids": list(resolution.rule_ids),
                }
            )
    declared = set((task.get("scope") or {}).get("modules") or ())
    return {
        "status": "valid" if not diagnostics and actual <= declared else "blocked",
        "declared_modules": sorted(declared),
        "actual_modules": sorted(actual),
        "unexpected_modules": sorted(actual - declared),
        "diagnostics": diagnostics,
        "changes": [asdict(record) for record in changed],
    }
