"""Bounded request-local proof derivation for automatic Plan reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import yaml
from jsonschema import ValidationError, validate

from .collect_evidence import command_covers_test, record_covers_test
from .evidence_validator import (
    EvidenceStatus,
    EvidenceValidationError,
    project_evidence,
)
from .schema_resources import read_schema
from .workspace import changed_paths_since, protected_paths_fingerprint

_MAX_CANDIDATES = 16
_MAX_ATOMS = 16


class PlanAutomationError(ValueError):
    """Stable refusal raised when mechanical proof cannot be selected."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, order=True)
class ProofAtom:
    kind: str
    value: str


@dataclass(frozen=True)
class EvidenceCandidate:
    ref: str
    coverage: int


@dataclass(frozen=True)
class AutoProofSelection:
    evidence_refs: tuple[str, ...]
    surface_refs: tuple[str, ...]


@dataclass(frozen=True)
class MechanicalSurfaceFacts:
    changed: frozenset[str]
    usable: frozenset[str]
    protected: frozenset[str]
    protected_fingerprint_changed: bool


def select_unique_minimum_cover(
    required_mask: int,
    candidates: tuple[EvidenceCandidate, ...],
) -> tuple[str, ...]:
    """Return sole minimum-cardinality exact cover within closed P2 limits."""
    if required_mask <= 0:
        raise PlanAutomationError("PLAN_PROOF_MISSING")
    if len(candidates) > _MAX_CANDIDATES or required_mask.bit_count() > _MAX_ATOMS:
        raise PlanAutomationError("PLAN_AUTO_LIMIT_EXCEEDED")

    ordered = tuple(sorted(candidates, key=lambda candidate: candidate.ref))
    for size in range(1, len(ordered) + 1):
        found: tuple[str, ...] | None = None
        for group in combinations(ordered, size):
            coverage = 0
            for candidate in group:
                coverage |= candidate.coverage
            if coverage & required_mask != required_mask:
                continue
            selected = tuple(candidate.ref for candidate in group)
            if found is not None:
                raise PlanAutomationError("PLAN_AUTO_PROOF_AMBIGUOUS")
            found = selected
        if found is not None:
            return found
    raise PlanAutomationError("PLAN_PROOF_MISSING")


def mechanical_surface_facts(
    task: dict,
    plan: dict,
    *,
    repo_root: Path | None = None,
    _changed_paths=None,
    _protected_fingerprint=None,
) -> MechanicalSurfaceFacts:
    """Return one shared P0-filtered mechanical surface snapshot."""
    changed_paths = _changed_paths or changed_paths_since
    protected_fingerprint = _protected_fingerprint or protected_paths_fingerprint
    user_changes = (task.get("risk") or {}).get("user_changes", {})
    protected = frozenset(user_changes.get("paths", []))
    protected_digest = user_changes.get("fingerprint")
    if protected:
        protected_digest = (
            protected_fingerprint(tuple(sorted(protected)))
            if repo_root is None
            else protected_fingerprint(tuple(sorted(protected)), repo_root=repo_root)
        )
    protected_changed = bool(protected) and (
        protected_digest != user_changes.get("fingerprint")
    )
    needs_surfaces = any(item.get("surfaces", []) for item in plan.get("items", []))
    changed_values = ()
    if needs_surfaces:
        base_commit = task.get("git", {}).get("base_commit") or "HEAD"
        changed_values = (
            changed_paths(base_commit)
            if repo_root is None
            else changed_paths(base_commit, repo_root=repo_root)
        )
    changed = frozenset(changed_values)
    usable = changed if protected_changed else changed - protected
    return MechanicalSurfaceFacts(changed, frozenset(usable), protected, protected_changed)


def _qualified_cases(harness_dir: Path) -> dict[str, dict[str, dict]]:
    from harness import source_access

    cases: dict[str, dict[str, dict]] = {}
    for filename, key, schema_name in (
        ("requirements.yaml", "requirements", "requirement.schema.json"),
        ("invariants.yaml", "invariants", "invariant.schema.json"),
    ):
        path = harness_dir / filename
        try:
            document = yaml.safe_load(source_access.read_text(path, encoding="utf-8"))
            validate(document, read_schema(schema_name))
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as exc:
            raise EvidenceValidationError(f"PLAN_SOURCE_INVALID: {path}") from exc
        for record in document[key]:
            cases[record["id"]] = {
                case["id"]: case
                for case in (record.get("test_plan") or {}).get("cases", [])
            }
    return cases


def _proof_atoms(
    references: list[str], cases: dict[str, dict[str, dict]]
) -> tuple[ProofAtom, ...]:
    atoms: set[ProofAtom] = set()
    try:
        for reference in references:
            parent, case_id = reference.split("/", 1)
            case = cases[parent][case_id]
            if case.get("strategy") == "manual":
                atoms.add(ProofAtom("manual", case_id))
            else:
                atoms.update(
                    ProofAtom("automated", node) for node in case.get("tests", [])
                )
    except (KeyError, ValueError) as exc:
        raise PlanAutomationError("PLAN_DISPOSITION_INVALID") from exc
    return tuple(sorted(atoms))


def _candidate_coverage(record: dict, atoms: tuple[ProofAtom, ...]) -> int:
    coverage = 0
    for index, atom in enumerate(atoms):
        if atom.kind == "manual":
            covered = atom.value in record.get("covered_test_cases", [])
        else:
            covered = record_covers_test(record, atom.value) and command_covers_test(
                record.get("command") or "", atom.value
            )
        if covered:
            coverage |= 1 << index
    return coverage


def _select_evidence(
    harness_dir: Path,
    references: list[str],
    *,
    head: str,
    workspace: str,
) -> tuple[str, ...]:
    from harness import source_access

    evidence_dir = harness_dir / "evidence"
    requirement_path = harness_dir / "requirements.yaml"
    invariant_path = harness_dir / "invariants.yaml"
    with source_access.source_scope(
        harness_dir,
        allowed=(requirement_path, invariant_path, evidence_dir),
        member_rules=((evidence_dir, "*.json"),),
    ):
        cases = _qualified_cases(harness_dir)
        atoms = _proof_atoms(references, cases)
        if not atoms:
            raise PlanAutomationError("PLAN_PROOF_MISSING")
        if len(atoms) > _MAX_ATOMS:
            raise PlanAutomationError("PLAN_AUTO_LIMIT_EXCEEDED")

        candidates: list[EvidenceCandidate] = []
        for path in source_access.members(evidence_dir, "*.json"):
            projection = project_evidence(path, head, workspace)
            if projection.status is EvidenceStatus.INVALID:
                raise EvidenceValidationError(f"PLAN_SOURCE_INVALID: {path}")
            if projection.status is not EvidenceStatus.FRESH or projection.record is None:
                continue
            coverage = _candidate_coverage(projection.record, atoms)
            if coverage:
                candidates.append(EvidenceCandidate(path.name[:-5], coverage))

    return select_unique_minimum_cover((1 << len(atoms)) - 1, tuple(candidates))


def derive_auto_proof(
    harness_dir: Path,
    task: dict,
    plan: dict,
    item: dict,
    *,
    head: str,
    workspace: str,
) -> AutoProofSelection:
    """Derive request-local COMPLETE proof without mutating canonical state."""
    test_refs = item.get("test_case_refs", [])
    surfaces = item.get("surfaces", [])
    if not (test_refs or surfaces):
        raise PlanAutomationError("PLAN_DISPOSITION_INVALID")

    evidence_refs = (
        _select_evidence(harness_dir, test_refs, head=head, workspace=workspace)
        if test_refs
        else ()
    )
    surface_refs: tuple[str, ...] = ()
    if surfaces:
        facts = mechanical_surface_facts(task, plan, repo_root=harness_dir.parent)
        surface_refs = tuple(sorted(set(surfaces) & facts.usable))
        if not surface_refs:
            raise PlanAutomationError("PLAN_PROOF_MISSING")
    return AutoProofSelection(evidence_refs, surface_refs)
