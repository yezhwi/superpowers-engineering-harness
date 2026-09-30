"""Request-local Architecture assessment for Quality Gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from harness import source_access, workspace
from harness.architecture import (
    ArchitectureError,
    ArchitectureModel,
    architecture_fingerprint,
    ownership_match_score,
    resolve_ownership,
)
from harness.architecture_store import load_architecture
from harness.blockers import RECOVERY_POLICY, GateBlocker
from harness.schema_resources import read_schema

from jsonschema import ValidationError, validate


class ArchitectureGateError(ValueError):
    """Malformed Architecture control state, never a persisted blocker."""


@dataclass(frozen=True)
class ArchitectureAssessment:
    blockers: tuple[GateBlocker, ...]
    model: ArchitectureModel | None
    declared_modules: tuple[str, ...]
    relevant_modules: tuple[str, ...]
    sealed_fingerprint: str | None = None


def _block(code: str, message: str, source: str) -> GateBlocker:
    return GateBlocker(
        code,
        "implementation",
        message,
        source=source,
        recover_to=RECOVERY_POLICY.get(code),
    )


def _contract_changed(message: str) -> ArchitectureAssessment:
    return ArchitectureAssessment(
        (
            GateBlocker(
                "CONTRACT_CHANGED",
                "implementation",
                message,
                source="artifact:.harness/alignment-freeze.yaml",
                recover_to=RECOVERY_POLICY["CONTRACT_CHANGED"],
            ),
        ),
        None,
        (),
        (),
    )


def _load_seal(harness_dir: Path) -> dict | None:
    path = harness_dir / "alignment-freeze.yaml"
    if not source_access.is_file(path):
        return None
    try:
        document = yaml.safe_load(source_access.read_text(path))
        validate(document, read_schema("alignment-freeze.schema.json"))
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as exc:
        raise ArchitectureGateError("ALIGNMENT_FREEZE_INVALID") from exc
    return document


def assess_architecture(
    harness_dir: Path,
    task: dict,
    gate_config: dict,
    *,
    allow_preflight: bool,
) -> ArchitectureAssessment:
    """Assess one task without persistence, inference, or duplicate Git snapshots."""
    del allow_preflight  # Assessment semantics are identical; caller controls persistence.
    risk = task.get("risk") or {}
    if risk.get("profile") == "FAST" or risk.get("level") == "Q1":
        return ArchitectureAssessment((), None, (), ())
    mode = (gate_config.get("architecture") or {}).get("mode", "off")
    if mode == "off":
        return ArchitectureAssessment((), None, (), ())
    if mode != "required":
        raise ArchitectureGateError("ARCHITECTURE_MODE_INVALID")

    seal = _load_seal(harness_dir)
    if (
        seal is None
        or seal.get("version") != 2
        or seal.get("task_id") != (task.get("task") or {}).get("id")
        or seal.get("architecture_mode") != "required"
    ):
        return _contract_changed("Architecture mode is not sealed as required")

    scope = task.get("scope") or {}
    if "modules" not in scope:
        return _contract_changed("declared Architecture modules changed")
    declared = tuple(scope["modules"])
    if sorted(seal["declared_modules"]) != sorted(declared):
        return _contract_changed("declared Architecture modules changed")

    artifact = harness_dir / "architecture.yaml"
    if not source_access.is_file(artifact):
        return ArchitectureAssessment(
            (
                _block(
                    "ARCHITECTURE_REQUIRED",
                    "required Architecture artifact is missing",
                    "artifact:.harness/architecture.yaml",
                ),
            ),
            None,
            tuple(sorted(declared)),
            (),
            seal["architecture_fingerprint"],
        )
    try:
        model = load_architecture(harness_dir, required=True)
    except ArchitectureError as exc:
        raise ArchitectureGateError(str(exc)) from exc
    assert model is not None
    fingerprint = architecture_fingerprint(model)
    if fingerprint != seal["architecture_fingerprint"]:
        return _contract_changed("Architecture fingerprint changed")

    blockers: list[GateBlocker] = []
    known_modules = {module.id for module in model.modules}
    blockers.extend(
        _block(
            "ARCHITECTURE_SCOPE_INVALID",
            f"declared Architecture module does not exist: {module_id}",
            f"module:{module_id}",
        )
        for module_id in sorted(set(declared) - known_modules)
    )

    try:
        path_index = workspace.architecture_path_index(harness_dir.parent)
        changes = workspace.architecture_changes(
            task["git"]["base_commit"], harness_dir.parent
        )
    except (workspace.WorkspaceError, KeyError, TypeError) as exc:
        raise ArchitectureGateError("ARCHITECTURE_CHANGESET_INVALID") from exc
    current_paths = set(path_index)
    for module in model.modules:
        for evidence in module.evidence:
            if evidence.path not in current_paths:
                blockers.append(
                    _block(
                        "ARCHITECTURE_EVIDENCE_INVALID",
                        f"Architecture evidence path is missing: {evidence.path}",
                        f"path:{evidence.path}",
                    )
                )

    preexisting = set((risk.get("user_changes") or {}).get("paths") or ())
    owned = set(scope.get("owned_paths") or ())
    excluded = preexisting - owned
    attributable = tuple(record for record in changes if record.path not in excluded)
    relevant: set[str] = set()
    declared_set = set(declared)
    by_path = sorted({record.path for record in attributable})
    for path in by_path:
        resolution = resolve_ownership(model, path)
        if resolution.status == "unresolved":
            blockers.append(
                _block(
                    "ARCHITECTURE_OWNERSHIP_UNRESOLVED",
                    f"Architecture ownership is unresolved: {path}",
                    f"path:{path}",
                )
            )
            continue
        if resolution.status == "ambiguous":
            blockers.append(
                _block(
                    "ARCHITECTURE_OWNERSHIP_AMBIGUOUS",
                    f"Architecture ownership is ambiguous: {path}",
                    f"path:{path}",
                )
            )
            continue
        relevant.update(resolution.modules)
        for module_id in sorted(set(resolution.modules) - declared_set):
            blockers.append(
                _block(
                    "ARCHITECTURE_SCOPE_DRIFT",
                    f"changed path belongs to undeclared module {module_id}: {path}",
                    f"path:{path}|module:{module_id}",
                )
            )

    deleted_paths = {
        record.path for record in attributable if record.kind == "deleted"
    }
    for rule in model.ownership:
        if rule.allow_empty or not any(
            ownership_match_score(rule, path) is not None for path in deleted_paths
        ):
            continue
        if not any(
            ownership_match_score(rule, path) is not None for path in path_index
        ):
            blockers.append(
                _block(
                    "ARCHITECTURE_OWNERSHIP_EMPTY",
                    f"Architecture ownership rule became empty: {rule.id}",
                    f"ownership:{rule.id}",
                )
            )

    unique = {
        (blocker.code, blocker.source): blocker
        for blocker in blockers
    }
    ordered = tuple(
        unique[key] for key in sorted(unique, key=lambda item: (item[0], item[1] or ""))
    )
    return ArchitectureAssessment(
        ordered,
        model,
        tuple(sorted(declared)),
        tuple(sorted(relevant)),
        fingerprint,
    )
