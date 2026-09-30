"""Architecture artifact loading, publication, and read-only workspace projection."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import yaml

from harness import source_access, transaction, workspace
from harness.architecture import (
    ArchitectureError,
    ArchitectureModel,
    architecture_context_summary,
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
    if source_access.is_symlink(path):
        raise ArchitectureError("ARCHITECTURE_SCHEMA_INVALID", "artifact must be a regular repository file")
    if not source_access.exists(path):
        if required:
            raise ArchitectureError("ARCHITECTURE_REQUIRED")
        return None
    if not source_access.is_file(path):
        raise ArchitectureError("ARCHITECTURE_SCHEMA_INVALID", "artifact must be a regular repository file")
    try:
        content = source_access.read_regular_bytes_beneath(path, harness_dir.parent)
    except OSError as exc:
        raise ArchitectureError(
            "ARCHITECTURE_SCHEMA_INVALID", "artifact must be a regular repository file"
        ) from exc
    return load_architecture_document(
        _load_yaml_bytes(content), source_size_bytes=len(content)
    )


def _task_attributable_changes(task: dict, repo_root: Path) -> tuple:
    git = task.get("git")
    if not isinstance(git, dict):
        raise ArchitectureError("ARCHITECTURE_CHANGESET_INVALID")
    base = git.get("base_commit")
    if base is None:
        return ()
    if not isinstance(base, str) or not base:
        raise ArchitectureError("ARCHITECTURE_CHANGESET_INVALID")
    risk = task.get("risk")
    scope = task.get("scope")
    if risk is not None and not isinstance(risk, dict):
        raise ArchitectureError("ARCHITECTURE_TASK_INVALID")
    if scope is not None and not isinstance(scope, dict):
        raise ArchitectureError("ARCHITECTURE_TASK_INVALID")
    user_changes = (risk or {}).get("user_changes")
    if user_changes is not None and not isinstance(user_changes, dict):
        raise ArchitectureError("ARCHITECTURE_TASK_INVALID")
    excluded = set((user_changes or {}).get("paths") or ())
    excluded -= set((scope or {}).get("owned_paths") or ())
    try:
        changes = workspace.architecture_changes(base, repo_root)
    except workspace.WorkspaceError as exc:
        raise ArchitectureError("ARCHITECTURE_CHANGESET_INVALID") from exc
    return tuple(record for record in changes if record.path not in excluded)


def _validate_publication(
    model: ArchitectureModel, repo_root: Path, task: dict | None = None
) -> tuple[str, ...]:
    paths = workspace.architecture_path_index(repo_root)
    path_set = set(paths)
    for module in model.modules:
        for evidence in module.evidence:
            evidence_path = repo_root / evidence.path
            if evidence.path not in path_set or not source_access.is_regular_file_beneath(
                evidence_path, repo_root
            ):
                raise ArchitectureError(
                    "ARCHITECTURE_EVIDENCE_INVALID", evidence.path
                )
    coverage_paths = set(paths)
    if task is not None:
        coverage_paths.update(
            record.path for record in _task_attributable_changes(task, repo_root)
        )
    for rule in model.ownership:
        if not rule.allow_empty and not any(
            ownership_match_score(rule, path) is not None for path in coverage_paths
        ):
            raise ArchitectureError("ARCHITECTURE_OWNERSHIP_EMPTY", rule.id)
    for path in paths:
        if resolve_ownership(model, path).status == "ambiguous":
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
        _validate_publication(model, harness_dir.parent, task)
        artifact = harness_dir / _ARCHITECTURE_ARTIFACT
        if source_access.is_symlink(artifact) or (
            source_access.exists(artifact) and not source_access.is_file(artifact)
        ):
            raise ArchitectureError(
                "ARCHITECTURE_SCHEMA_INVALID",
                "artifact must be a regular repository file",
            )
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
        scope.setdefault("owned_paths", [])
        scope.setdefault("protected_user_paths", [])
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
    task, _ = _load_task(harness_dir)
    _validate_publication(model, harness_dir.parent, task)
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


def _architecture_assessment(harness_dir: Path):
    from harness import quality_gate
    from harness.architecture_gate import ArchitectureGateError, assess_architecture

    task, _ = _load_task(harness_dir)
    gate_path = harness_dir / "gate.yaml"
    try:
        gate = yaml.safe_load(source_access.read_text(gate_path))
        quality_gate.validate_schema(gate, "gate.schema.json", gate_path)
        return assess_architecture(
            harness_dir, task, gate["gate"], allow_preflight=True
        )
    except (
        ArchitectureGateError,
        quality_gate.InvalidHarnessState,
        OSError,
        UnicodeError,
        yaml.YAMLError,
        KeyError,
        TypeError,
    ) as exc:
        raise ArchitectureError("ARCHITECTURE_CHECK_INVALID") from exc


def summary_architecture(harness_dir: Path) -> dict:
    """Return same bounded Architecture projection consumed by Context."""
    assessment = _architecture_assessment(harness_dir)
    return architecture_context_summary(assessment.model, assessment)


def check_architecture(harness_dir: Path) -> dict:
    """Run the same read-only Architecture assessment consumed by Gate."""
    assessment = _architecture_assessment(harness_dir)
    return {
        "status": "valid" if not assessment.blockers else "blocked",
        "declared_modules": list(assessment.declared_modules),
        "actual_modules": list(assessment.relevant_modules),
        "unexpected_modules": sorted(
            {
                (blocker.source or "").rsplit("module:", 1)[1]
                for blocker in assessment.blockers
                if blocker.code == "ARCHITECTURE_SCOPE_DRIFT"
            }
        ),
        "diagnostics": [
            {"code": blocker.code, "source": blocker.source}
            for blocker in assessment.blockers
        ],
        "blockers": [asdict(blocker) for blocker in assessment.blockers],
        "changes": [asdict(record) for record in assessment.attributable_changes],
    }
