"""Canonical implementation-plan fingerprinting and reconciliation helpers."""

import hashlib
import json
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import yaml
from jsonschema import ValidationError, validate

from . import plan_automation
from .blockers import GateBlocker
from .collect_evidence import command_covers_test, record_covers_test
from .evidence_validator import EvidenceStatus, project_evidence
from .paths import EvidenceReferenceError, evidence_path
from .plan_execution import (
    PlanExecutionError,
    ReplayResult,
    append_plan_transition,
    replay_plan_execution,
)
from .schema_resources import read_schema
from .telemetry_lock import telemetry_lock
from .transaction import atomic_write
from .workspace import changed_paths_since, protected_paths_fingerprint
from .workspace import snapshot as workspace_snapshot

_OPTIONAL_ITEM_LISTS = (
    "requirement_refs",
    "test_case_refs",
    "invariant_refs",
    "surfaces",
)


def plan_fingerprint(plan: dict) -> str:
    """Return stable digest for semantic plan content, excluding execution state."""
    items = []
    for item in plan["items"]:
        normalized = {"id": item["id"], "intent": item["intent"]}
        normalized.update({name: item.get(name, []) for name in _OPTIONAL_ITEM_LISTS})
        items.append(normalized)
    payload = json.dumps(
        {"version": plan["version"], "items": items},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class PlanArtifactError(ValueError):
    """Canonical plan artifact is unreadable or schema-invalid."""


class PlanMutationError(ValueError):
    """Stable task-level Plan mutation refusal."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PlanMutationRequest:
    action: str
    item_id: str | None = None
    disposition: str | None = None
    reason: str | None = None
    evidence_refs: tuple[str, ...] = ()
    surface_refs: tuple[str, ...] = ()
    decision_id: str | None = None
    replacements: tuple[str, ...] = ()
    auto: bool = False


@dataclass(frozen=True)
class PlanIssue:
    code: str
    message: str


@dataclass(frozen=True)
class PlanAssessment:
    blockers: tuple[GateBlocker, ...]
    final_blockers: tuple[GateBlocker, ...]
    projection: dict[str, dict] | None
    replay: ReplayResult | None
    plan: dict | None = None


def effective_plan_reconciliation(task: dict) -> dict:
    """Return effective Context/Gate plan configuration for current profile."""
    configuration = task.get("plan_reconciliation") or {}
    profile = (task.get("risk") or {}).get("profile")
    if configuration.get("enabled") is not True or profile not in {
        "STANDARD",
        "STRICT",
    }:
        return {"enabled": False}
    return {"enabled": True, "mode": configuration["mode"]}


def _load_yaml(path: Path, schema_name: str) -> tuple[dict | None, PlanIssue | None]:
    from harness import source_access

    try:
        document = yaml.safe_load(source_access.read_text(path, encoding="utf-8"))
        validate(document, read_schema(schema_name))
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as exc:
        raise PlanArtifactError(f"PLAN_SCHEMA_INVALID: {path}") from exc
    if schema_name == "plan.schema.json":
        item_ids = [item["id"] for item in document["items"]]
        if len(item_ids) != len(set(item_ids)):
            raise PlanArtifactError("PLAN_ITEM_ID_DUPLICATE")
    return document, None


def load_plan_artifacts(
    harness_dir: Path, *, optional: bool = False
) -> tuple[dict | None, dict | None]:
    """Load canonical plan documents while preserving per-file absence."""
    from harness import source_access

    loaded: list[dict | None] = []
    for name, schema_name in (
        ("plan.yaml", "plan.schema.json"),
        ("plan-execution.yaml", "plan-execution.schema.json"),
    ):
        path = harness_dir / name
        if not source_access.is_file(path):
            if not optional:
                raise PlanArtifactError(f"PLAN_REQUIRED: {path}")
            loaded.append(None)
            continue
        document, _ = _load_yaml(path, schema_name)
        loaded.append(document)
    return loaded[0], loaded[1]


def _plan_initialization_issues(
    plan: dict | None, execution: dict | None
) -> list[PlanIssue]:
    """Validate one already-loaded canonical plan/execution pair."""
    if plan is None or execution is None:
        return [PlanIssue("PLAN_REQUIRED", "enabled task requires plan artifacts")]
    if execution["plan"]["fingerprint"] != plan_fingerprint(plan):
        return [PlanIssue("PLAN_STALE", "plan fingerprint does not match canonical plan")]
    plan_ids = {item["id"] for item in plan["items"]}
    if unknown := set(execution["items"]) - plan_ids:
        return [
            PlanIssue(
                "PLAN_DISPOSITION_INVALID",
                f"execution item is absent from plan: {min(unknown)}",
            )
        ]
    return []


def validate_plan_initialization(
    harness_dir: Path, task: dict | None = None
) -> list[PlanIssue]:
    """Validate artifacts needed before enabled task implementation begins."""
    if task is not None and not effective_plan_reconciliation(task)["enabled"]:
        return []
    plan, execution = load_plan_artifacts(harness_dir, optional=True)
    issues = _plan_initialization_issues(plan, execution)
    if issues:
        return issues
    assert plan is not None and execution is not None
    configuration = effective_plan_reconciliation(task or {})
    task_level = (
        configuration.get("enabled") is True
        and configuration.get("mode") == "task_and_final"
        and ((task or {}).get("risk") or {}).get("profile") == "STRICT"
    )
    if task_level:
        if execution["version"] != 2:
            return [
                PlanIssue(
                    "PLAN_TASK_LEVEL_REQUIRED",
                    "task-level plan execution history requires execution v2",
                )
            ]
        replay = replay_plan_execution(plan, execution)
        if replay.issues:
            return [
                PlanIssue(
                    "PLAN_SEQUENCE_INVALID",
                    f"plan execution journal cannot replay: {replay.issues[0].code}",
                )
            ]
        if execution["sequence"] != 0 or execution["transitions"] or execution["items"]:
            return [
                PlanIssue(
                    "PLAN_SEQUENCE_INVALID",
                    "task-level implementation entry requires empty execution v2",
                )
            ]
    elif task is not None and execution["version"] != 1:
        return [
            PlanIssue(
                "PLAN_DISPOSITION_INVALID",
                "final-only task requires plan execution v1",
            )
        ]
    return []


def _assessment_projection(
    plan: dict | None,
    execution: dict | None,
    assessment: PlanAssessment | Iterable[GateBlocker],
) -> tuple[tuple[GateBlocker, ...], tuple[GateBlocker, ...], dict | None]:
    if isinstance(assessment, PlanAssessment):
        return assessment.blockers, assessment.final_blockers, assessment.projection
    blockers = tuple(assessment)
    trustworthy = (
        plan is not None
        and execution is not None
        and execution["plan"]["fingerprint"] == plan_fingerprint(plan)
    )
    return blockers, blockers, execution["items"] if trustworthy else None


def plan_context_summary(
    task: dict,
    plan: dict | None,
    execution: dict | None,
    assessment: PlanAssessment | Iterable[GateBlocker],
) -> dict:
    """Project body-free Plan Reconciliation state from already-loaded facts."""
    configuration = effective_plan_reconciliation(task)
    if not configuration["enabled"]:
        return configuration
    _, final_blockers, projection = _assessment_projection(
        plan, execution, assessment
    )
    next_item = None
    if plan is not None and projection is not None:
        for item in plan["items"]:
            record = projection.get(item["id"])
            if record is None or record["status"] in {
                "PENDING",
                "IN_PROGRESS",
                "BLOCKED",
            }:
                next_item = item["id"]
                break
    return {
        **configuration,
        "next_plan_item": next_item,
        "final_status": (
            "blocked"
            if any(blocker.code.startswith("PLAN_") for blocker in final_blockers)
            else "pass"
        ),
    }


def plan_status_report(
    task: dict,
    plan: dict | None,
    execution: dict | None,
    assessment: PlanAssessment | Iterable[GateBlocker],
) -> dict:
    """Project compact read-only status from one loaded plan assessment."""
    configuration = effective_plan_reconciliation(task)
    if not configuration["enabled"]:
        return configuration

    blocker_list, _, projection = _assessment_projection(
        plan, execution, assessment
    )
    summary = plan_context_summary(
        task,
        plan,
        execution,
        assessment if isinstance(assessment, PlanAssessment) else blocker_list,
    )
    fingerprint = plan_fingerprint(plan) if plan is not None else None
    execution_fingerprint = (
        execution["plan"]["fingerprint"] if execution is not None else None
    )
    fingerprint_fresh = (
        fingerprint == execution_fingerprint
        if fingerprint is not None and execution_fingerprint is not None
        else None
    )
    progress = None
    if plan is not None and projection is not None:
        statuses = {
            status: 0
            for status in (
                "PENDING",
                "IN_PROGRESS",
                "COMPLETE",
                "SKIPPED",
                "SUPERSEDED",
                "BLOCKED",
            )
        }
        reconciled = 0
        for item in plan["items"]:
            record = projection.get(item["id"])
            if record is None:
                continue
            status = record["status"]
            statuses[status] += 1
            if status in {"COMPLETE", "SKIPPED", "SUPERSEDED"}:
                reconciled += 1
        progress = {
            "total": len(plan["items"]),
            "reconciled": reconciled,
            "statuses": statuses,
        }
    return {
        **configuration,
        "plan": {
            "present": plan is not None,
            "execution_present": execution is not None,
            "fingerprint": fingerprint,
            "execution_fingerprint": execution_fingerprint,
            "fingerprint_fresh": fingerprint_fresh,
        },
        "progress": progress,
        "next_plan_item": summary["next_plan_item"],
        "final_status": summary["final_status"],
        "blockers": [
            {
                "code": blocker.code,
                "source": blocker.source,
                "message": blocker.message,
            }
            for blocker in blocker_list
        ],
    }


def _blocker(issue: PlanIssue, *, source: str | None = None) -> GateBlocker:
    return GateBlocker(
        issue.code,
        "implementation",
        issue.message,
        source=source,
        recover_to="IMPLEMENTING",
    )


def _fresh_item_evidence(harness_dir: Path, references: list[str], head: str, workspace: str) -> bool:
    try:
        return all(
            project_evidence(evidence_path(harness_dir, reference), head, workspace).status
            is EvidenceStatus.FRESH
            for reference in references
        )
    except EvidenceReferenceError:
        return False


def _latest_receipt_matches(
    harness_dir: Path,
    record: dict,
    receipt: dict | None,
    *,
    head: str,
    workspace: str,
) -> bool:
    """Require current proof identity to match latest accepted v2 receipt."""
    from harness import source_access

    if (
        not isinstance(receipt, dict)
        or receipt.get("head") != head
        or receipt.get("workspace") != workspace
        or receipt.get("surface_refs") != record.get("surface_refs", [])
    ):
        return False
    evidence_refs = record.get("evidence_refs", [])
    evidence_receipts = receipt.get("evidence")
    if (
        not isinstance(evidence_receipts, list)
        or [entry.get("ref") for entry in evidence_receipts] != evidence_refs
    ):
        return False
    try:
        for entry in evidence_receipts:
            content = source_access.read_bytes(
                evidence_path(harness_dir, entry["ref"])
            )
            digest = "sha256:" + hashlib.sha256(content).hexdigest()
            if digest != entry.get("sha256"):
                return False
    except (OSError, KeyError, TypeError, EvidenceReferenceError):
        return False
    return True


def _qualified_cases(harness_dir: Path) -> dict[str, dict]:
    from harness import source_access

    cases: dict[str, dict] = {}
    for filename, key, schema_name in (
        ("requirements.yaml", "requirements", "requirement.schema.json"),
        ("invariants.yaml", "invariants", "invariant.schema.json"),
    ):
        path = harness_dir / filename
        try:
            document = yaml.safe_load(source_access.read_text(path, encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise PlanArtifactError(f"PLAN_SOURCE_INVALID: {path}") from exc
        try:
            validate(document, read_schema(schema_name))
        except ValidationError as exc:
            raise PlanArtifactError(f"PLAN_SOURCE_INVALID: {path}") from exc
        for record in document[key]:
            cases[record["id"]] = {
                case["id"]: case
                for case in (record.get("test_plan") or {}).get("cases", [])
            }
    return cases


def _manual_cases_are_covered(
    harness_dir: Path,
    test_case_refs: list[str],
    evidence_refs: list[str],
    qualified_cases: dict[str, dict],
    head: str,
    workspace: str,
) -> bool:
    records = [
        project_evidence(evidence_path(harness_dir, reference), head, workspace).record
        for reference in evidence_refs
    ]
    for reference in test_case_refs:
        parent, case_id = reference.split("/", 1)
        case = qualified_cases[parent][case_id]
        if case.get("strategy") == "manual" and not any(
            case_id in (record or {}).get("covered_test_cases", [])
            for record in records
        ):
            return False
    return True


def _automated_cases_are_covered(
    harness_dir: Path,
    test_case_refs: list[str],
    evidence_refs: list[str],
    qualified_cases: dict[str, dict],
    head: str,
    workspace: str,
) -> bool:
    records = [
        project_evidence(evidence_path(harness_dir, reference), head, workspace).record
        for reference in evidence_refs
    ]
    for reference in test_case_refs:
        parent, case_id = reference.split("/", 1)
        case = qualified_cases[parent][case_id]
        if case.get("strategy") == "manual":
            continue
        for node_id in case.get("tests", []):
            if not any(
                record
                and record_covers_test(record, node_id)
                and command_covers_test(record.get("command") or "", node_id)
                for record in records
            ):
                return False
    return True


def _supersession_issue(plan: dict, items: dict) -> tuple[str, str] | None:
    plan_ids = {item["id"] for item in plan["items"]}
    graph: dict[str, list[str]] = {}
    for item_id, record in items.items():
        if record["status"] != "SUPERSEDED":
            continue
        replacements = record.get("superseded_by")
        if not isinstance(replacements, list) or not replacements:
            return item_id, "superseded item requires replacements"
        if any(replacement not in plan_ids for replacement in replacements):
            return item_id, "superseded replacement is absent from plan"
        graph[item_id] = replacements

    def has_cycle(node: str, trail: set[str]) -> bool:
        return node in trail or any(
            has_cycle(next_node, trail | {node}) for next_node in graph.get(node, [])
        )

    for item_id in graph:
        if has_cycle(item_id, set()):
            return item_id, "supersession cycle"
    return None


def validate_plan_reconciliation(
    harness_dir: Path, task: dict, *, head: str, workspace: str
) -> list[GateBlocker]:
    """Load canonical documents once and return final-plan blockers."""
    plan, execution = load_plan_artifacts(harness_dir, optional=True)
    return validate_plan_reconciliation_documents(
        harness_dir,
        task,
        plan,
        execution,
        head=head,
        workspace=workspace,
    )


def _validate_p0_projection(
    harness_dir: Path,
    task: dict,
    plan: dict,
    items: dict[str, dict],
    *,
    head: str,
    workspace: str,
    latest_proof_receipts: dict[str, dict] | None = None,
    check_proof: bool = True,
) -> list[GateBlocker]:
    """Return existing final-state blockers for one explicit item projection."""
    plan_ids = {item["id"] for item in plan["items"]}
    if unknown := set(items) - plan_ids:
        return [
            GateBlocker(
                "PLAN_DISPOSITION_INVALID",
                "implementation",
                f"execution item is absent from plan: {min(unknown)}",
                recover_to="IMPLEMENTING",
            )
        ]

    if supersession := _supersession_issue(plan, items):
        item_id, message = supersession
        return [
            GateBlocker(
                "PLAN_DISPOSITION_INVALID",
                "implementation",
                message,
                source=item_id,
                recover_to="IMPLEMENTING",
            )
        ]

    from .decision import load_decisions

    task_id = task.get("task", {}).get("id")
    accepted_decisions = {
        record["id"]
        for record in load_decisions(harness_dir)
        if record["task_id"] == task_id and record["status"] == "ACCEPTED"
    }
    qualified_cases = _qualified_cases(harness_dir)
    user_changes = (task.get("risk") or {}).get("user_changes", {})
    protected = set(user_changes.get("paths", []))
    if check_proof:
        surface_facts = plan_automation.mechanical_surface_facts(
            task,
            plan,
            _changed_paths=changed_paths_since,
            _protected_fingerprint=protected_paths_fingerprint,
        )
        protected_changed = surface_facts.protected_fingerprint_changed
        changed_surfaces = set(surface_facts.usable)
    else:
        protected_changed = False
        changed_surfaces = set()

    blockers: list[GateBlocker] = []
    for item in plan["items"]:
        item_id = item["id"]
        record = items.get(item_id)
        if record is None or record["status"] in {"PENDING", "IN_PROGRESS", "BLOCKED"}:
            blockers.append(
                GateBlocker(
                    "PLAN_ITEM_UNRECONCILED",
                    "implementation",
                    "plan item lacks terminal reconciliation",
                    source=item_id,
                    recover_to="IMPLEMENTING",
                )
            )
            continue
        if (
            record["status"] == "COMPLETE"
            and item.get("surfaces", [])
            and protected_changed
            and protected & (set(item["surfaces"]) | set(record.get("surface_refs", [])))
        ):
            blockers.append(
                GateBlocker(
                    "PLAN_PROTECTED_PATHS_MODIFIED",
                    "implementation",
                    "complete surface item intersects modified protected user path",
                    source=item_id,
                    recover_to="IMPLEMENTING",
                )
            )
        invalid_contract_ref = next(
            (
                reference
                for reference in (
                    item.get("requirement_refs", [])
                    + item.get("invariant_refs", [])
                )
                if reference not in qualified_cases
            ),
            None,
        )
        invalid_case_ref = next(
            (
                reference
                for reference in item.get("test_case_refs", [])
                if reference.split("/", 1)[1]
                not in qualified_cases.get(reference.split("/", 1)[0], set())
            ),
            None,
        )
        if record.get("decision_id") and record["decision_id"] not in accepted_decisions:
            blockers.append(
                GateBlocker(
                    "PLAN_DISPOSITION_INVALID",
                    "implementation",
                    f"decision is not accepted for current task: {record['decision_id']}",
                    source=item_id,
                    recover_to="IMPLEMENTING",
                )
            )
        elif invalid_contract_ref:
            blockers.append(
                GateBlocker(
                    "PLAN_DISPOSITION_INVALID",
                    "implementation",
                    f"plan reference is absent: {invalid_contract_ref}",
                    source=item_id,
                    recover_to="IMPLEMENTING",
                )
            )
        elif invalid_case_ref:
            blockers.append(
                GateBlocker(
                    "PLAN_DISPOSITION_INVALID",
                    "implementation",
                    f"qualified test case is absent from parent: {invalid_case_ref}",
                    source=item_id,
                    recover_to="IMPLEMENTING",
                )
            )
        elif (
            check_proof
            and record["status"] == "COMPLETE"
            and latest_proof_receipts is not None
            and not _latest_receipt_matches(
                harness_dir,
                record,
                latest_proof_receipts.get(item_id),
                head=head,
                workspace=workspace,
            )
        ):
            blockers.append(
                GateBlocker(
                    "PLAN_PROOF_MISSING",
                    "verification",
                    "current proof does not match latest accepted receipt",
                    source=item_id,
                    recover_to="VERIFYING",
                )
            )
        elif (
            check_proof
            and record["status"] == "COMPLETE"
            and item.get("test_case_refs", [])
            and not record.get("evidence_refs", [])
        ):
            blockers.append(
                GateBlocker(
                    "PLAN_PROOF_MISSING",
                    "verification",
                    "complete test item lacks item-owned evidence",
                    source=item_id,
                    recover_to="VERIFYING",
                )
            )
        elif (
            check_proof
            and record["status"] == "COMPLETE"
            and item.get("test_case_refs", [])
            and not _fresh_item_evidence(
                harness_dir, record["evidence_refs"], head, workspace
            )
        ):
            blockers.append(
                GateBlocker(
                    "PLAN_PROOF_MISSING",
                    "verification",
                    "item-owned evidence is missing or stale",
                    source=item_id,
                    recover_to="VERIFYING",
                )
            )
        elif (
            check_proof
            and record["status"] == "COMPLETE"
            and item.get("test_case_refs", [])
            and not _manual_cases_are_covered(
                harness_dir,
                item["test_case_refs"],
                record["evidence_refs"],
                qualified_cases,
                head,
                workspace,
            )
        ):
            blockers.append(
                GateBlocker(
                    "PLAN_PROOF_MISSING",
                    "verification",
                    "manual case lacks item-owned coverage",
                    source=item_id,
                    recover_to="VERIFYING",
                )
            )
        elif (
            check_proof
            and record["status"] == "COMPLETE"
            and item.get("test_case_refs", [])
            and not _automated_cases_are_covered(
                harness_dir,
                item["test_case_refs"],
                record["evidence_refs"],
                qualified_cases,
                head,
                workspace,
            )
        ):
            blockers.append(
                GateBlocker(
                    "PLAN_PROOF_MISSING",
                    "verification",
                    "automated case lacks item-owned node coverage",
                    source=item_id,
                    recover_to="VERIFYING",
                )
            )
        elif (
            check_proof
            and record["status"] == "COMPLETE"
            and item.get("surfaces", [])
            and not record.get("surface_refs", [])
        ):
            blockers.append(
                GateBlocker(
                    "PLAN_PROOF_MISSING",
                    "verification",
                    "complete surface item lacks surface references",
                    source=item_id,
                    recover_to="VERIFYING",
                )
            )
        elif (
            record["status"] == "COMPLETE"
            and item.get("surfaces", [])
            and not set(record["surface_refs"]).issubset(item["surfaces"])
        ):
            blockers.append(
                GateBlocker(
                    "PLAN_DISPOSITION_INVALID",
                    "implementation",
                    "surface reference is not declared by item",
                    source=item_id,
                    recover_to="IMPLEMENTING",
                )
            )
        elif (
            check_proof
            and record["status"] == "COMPLETE"
            and item.get("surfaces", [])
            and not set(record["surface_refs"]).issubset(changed_surfaces)
        ):
            blockers.append(
                GateBlocker(
                    "PLAN_PROOF_MISSING",
                    "verification",
                    "declared surface reference is not changed",
                    source=item_id,
                    recover_to="VERIFYING",
                )
            )
        elif record["status"] == "COMPLETE" and not (
            item.get("test_case_refs", []) or item.get("surfaces", [])
        ):
            blockers.append(
                GateBlocker(
                    "PLAN_DISPOSITION_INVALID",
                    "implementation",
                    "complete item has no proof branch",
                    source=item_id,
                    recover_to="IMPLEMENTING",
                )
            )
        elif record["status"] == "SKIPPED" and not record.get("reason", "").strip():
            blockers.append(
                GateBlocker(
                    "PLAN_DISPOSITION_INVALID",
                    "implementation",
                    "skipped item requires reason",
                    source=item_id,
                    recover_to="IMPLEMENTING",
                )
            )
        elif record["status"] == "SUPERSEDED" and not record.get("reason", "").strip():
            blockers.append(
                GateBlocker(
                    "PLAN_DISPOSITION_INVALID",
                    "implementation",
                    "superseded item requires reason",
                    source=item_id,
                    recover_to="IMPLEMENTING",
                )
            )
    return blockers


def _artifact_early_blockers(
    plan: dict | None, execution: dict | None
) -> tuple[GateBlocker, ...]:
    if plan is None or execution is None:
        return (
            _blocker(
                PlanIssue("PLAN_REQUIRED", "enabled task requires plan artifacts")
            ),
        )
    if execution["plan"]["fingerprint"] != plan_fingerprint(plan):
        return (
            _blocker(
                PlanIssue(
                    "PLAN_STALE",
                    "plan fingerprint does not match canonical plan",
                )
            ),
        )
    return ()


def _mode_blocker(message: str) -> GateBlocker:
    return GateBlocker(
        "PLAN_DISPOSITION_INVALID",
        "implementation",
        message,
        recover_to="IMPLEMENTING",
    )


def _task_level_blocker(code: str, message: str) -> GateBlocker:
    return GateBlocker(
        code,
        "implementation",
        message,
        source=None,
        recover_to="IMPLEMENTING",
    )


def assess_plan_reconciliation_documents(
    harness_dir: Path,
    task: dict,
    plan: dict | None,
    execution: dict | None,
    *,
    head: str,
    workspace: str,
) -> PlanAssessment:
    """Assess public task-level trust and independent P0 final state."""
    early = _artifact_early_blockers(plan, execution)
    if early:
        return PlanAssessment(early, early, None, None, plan)
    assert plan is not None and execution is not None

    configuration = effective_plan_reconciliation(task)
    task_level = (
        configuration.get("enabled") is True
        and configuration.get("mode") == "task_and_final"
        and (task.get("risk") or {}).get("profile") == "STRICT"
    )

    if not task_level and execution["version"] != 1:
        blocker = _mode_blocker("final-only task requires plan execution v1")
        return PlanAssessment((blocker,), (blocker,), None, None, plan)

    if task_level and execution["version"] == 1:
        final = tuple(
            _validate_p0_projection(
                harness_dir,
                task,
                plan,
                execution["items"],
                head=head,
                workspace=workspace,
            )
        )
        blocker = _task_level_blocker(
            "PLAN_TASK_LEVEL_REQUIRED",
            "task-level plan execution history requires execution v2",
        )
        return PlanAssessment((blocker,), final, None, None, plan)

    if task_level:
        replay = replay_plan_execution(plan, execution)
        if replay.issues:
            final = tuple(
                _validate_p0_projection(
                    harness_dir,
                    task,
                    plan,
                    execution["items"],
                    head=head,
                    workspace=workspace,
                )
            )
            blocker = _task_level_blocker(
                "PLAN_SEQUENCE_INVALID",
                f"plan execution journal cannot replay: {replay.issues[0].code}",
            )
            return PlanAssessment((blocker,), final, None, replay, plan)
        projection = replay.items
    else:
        replay = None
        projection = execution["items"]

    final = tuple(
        _validate_p0_projection(
            harness_dir,
            task,
            plan,
            projection,
            head=head,
            workspace=workspace,
            latest_proof_receipts=(
                replay.latest_proof_receipts if replay is not None else None
            ),
        )
    )
    return PlanAssessment(final, final, projection, replay, plan)


def assess_plan_verification_entry_documents(
    harness_dir: Path,
    task: dict,
    plan: dict | None,
    execution: dict | None,
) -> list[GateBlocker]:
    """Require trusted terminal Q3 history without current final-proof checks."""
    configuration = effective_plan_reconciliation(task)
    task_level = (
        configuration.get("enabled") is True
        and configuration.get("mode") == "task_and_final"
        and (task.get("risk") or {}).get("profile") == "STRICT"
    )
    if not task_level:
        return []
    early = _artifact_early_blockers(plan, execution)
    if early:
        return early
    assert plan is not None and execution is not None
    if execution["version"] != 2:
        return [
            _task_level_blocker(
                "PLAN_TASK_LEVEL_REQUIRED",
                "task-level plan execution history requires execution v2",
            )
        ]
    replay = replay_plan_execution(plan, execution)
    if replay.issues:
        return [
            _task_level_blocker(
                "PLAN_SEQUENCE_INVALID",
                f"plan execution journal cannot replay: {replay.issues[0].code}",
            )
        ]
    return _validate_p0_projection(
        harness_dir,
        task,
        plan,
        replay.items,
        head="",
        workspace="",
        check_proof=False,
    )


def validate_plan_verification_entry(
    harness_dir: Path, task: dict
) -> list[GateBlocker]:
    """Load once and assess task-level readiness to enter verification."""
    plan, execution = load_plan_artifacts(harness_dir, optional=True)
    return assess_plan_verification_entry_documents(
        harness_dir, task, plan, execution
    )


def validate_plan_reconciliation_documents(
    harness_dir: Path,
    task: dict,
    plan: dict | None,
    execution: dict | None,
    *,
    head: str,
    workspace: str,
) -> list[GateBlocker]:
    """Return public blockers from one already-loaded plan assessment."""
    return list(
        assess_plan_reconciliation_documents(
            harness_dir,
            task,
            plan,
            execution,
            head=head,
            workspace=workspace,
        ).blockers
    )


_IMPLEMENTATION_ACTIONS = frozenset({"BEGIN", "BLOCK", "RESUME", "RECONCILE"})


def _mutation_state_allowed(task: dict, action: str) -> bool:
    state = task.get("state")
    if action in _IMPLEMENTATION_ACTIONS:
        return state == "IMPLEMENTING"
    if action == "REFRESH_PROOF":
        return state in {"IMPLEMENTING", "VERIFYING"}
    if action == "UPGRADE_EXECUTION":
        return state in {"SPECIFYING", "PLANNED", "IMPLEMENTING"}
    return False


def _normalize_mutation_request(
    plan: dict, request: PlanMutationRequest
) -> PlanMutationRequest:
    plan_order = {item["id"]: index for index, item in enumerate(plan["items"])}
    replacements = tuple(
        sorted(set(request.replacements), key=lambda item_id: plan_order.get(item_id, len(plan_order)))
    )
    return PlanMutationRequest(
        action=request.action,
        item_id=request.item_id,
        disposition=request.disposition,
        reason=request.reason,
        evidence_refs=tuple(sorted(set(request.evidence_refs))),
        surface_refs=tuple(sorted(set(request.surface_refs))),
        decision_id=request.decision_id,
        replacements=replacements,
        auto=request.auto,
    )


def _raise_artifact_issue(plan: dict | None, execution: dict | None) -> None:
    early = _artifact_early_blockers(plan, execution)
    if early:
        raise PlanMutationError(early[0].code)


def _upgrade_execution(plan: dict, execution: dict) -> dict | None:
    if execution["version"] == 2:
        replay = replay_plan_execution(plan, execution)
        if replay.issues:
            raise PlanMutationError("PLAN_SEQUENCE_INVALID")
        if execution["sequence"] == 0 and not execution["transitions"] and not execution["items"]:
            return None
        raise PlanMutationError("PLAN_TASK_LEVEL_REQUIRED")
    plan_ids = {item["id"] for item in plan["items"]}
    if set(execution["items"]) - plan_ids:
        raise PlanMutationError("PLAN_DISPOSITION_INVALID")
    if any(record["status"] != "PENDING" for record in execution["items"].values()):
        raise PlanMutationError("PLAN_TASK_LEVEL_REQUIRED")
    return {
        "version": 2,
        "plan": deepcopy(execution["plan"]),
        "sequence": 0,
        "transitions": [],
        "items": {},
    }


def _exact_transition_retry(
    execution: dict, request: PlanMutationRequest, transition: dict
) -> bool:
    if not execution["transitions"]:
        return False
    latest = execution["transitions"][-1]
    comparable = {key: value for key, value in latest.items() if key != "sequence"}
    return comparable == transition and latest.get("item") == request.item_id


def _evidence_receipts(
    harness_dir: Path,
    references: tuple[str, ...],
    *,
    head: str,
    workspace: str,
) -> list[dict]:
    from harness import source_access

    receipts: list[dict] = []
    for reference in references:
        try:
            path = evidence_path(harness_dir, reference)
            projection = project_evidence(path, head, workspace)
            if projection.status is EvidenceStatus.INVALID:
                raise PlanArtifactError(f"PLAN_SOURCE_INVALID: {path}")
            if projection.status is not EvidenceStatus.FRESH or projection.record is None:
                raise PlanMutationError("PLAN_PROOF_MISSING")
            content = source_access.read_bytes(path)
        except (OSError, EvidenceReferenceError) as exc:
            raise PlanMutationError("PLAN_PROOF_MISSING") from exc
        record = projection.record
        receipts.append(
            {
                "ref": reference,
                "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
                "type": record["type"],
                "exit_code": record["exit_code"],
                "commit": record["commit"],
                "workspace_fingerprint": record["workspace_fingerprint"],
            }
        )
    return receipts


def _proof_transition_payload(
    harness_dir: Path,
    task: dict,
    plan: dict,
    replay: ReplayResult,
    request: PlanMutationRequest,
    *,
    action: str,
    initial_snapshot=None,
) -> dict:
    before = initial_snapshot or workspace_snapshot(harness_dir.parent)
    evidence = _evidence_receipts(
        harness_dir,
        request.evidence_refs,
        head=before.head,
        workspace=before.fingerprint,
    )
    record = {"status": "COMPLETE"}
    if request.evidence_refs:
        record["evidence_refs"] = list(request.evidence_refs)
    if request.surface_refs:
        record["surface_refs"] = list(request.surface_refs)
    blockers = _validate_p0_projection(
        harness_dir,
        task,
        plan,
        {**replay.items, request.item_id: record},
        head=before.head,
        workspace=before.fingerprint,
    )
    target_blockers = [blocker for blocker in blockers if blocker.source == request.item_id]
    if target_blockers:
        raise PlanMutationError(target_blockers[0].code)
    after = workspace_snapshot(harness_dir.parent)
    if (after.head, after.fingerprint) != (before.head, before.fingerprint):
        raise PlanMutationError("PLAN_PROOF_MISSING")
    return {
        "item": request.item_id,
        "from": "COMPLETE" if action == "REFRESH_PROOF" else "IN_PROGRESS",
        "to": "COMPLETE",
        "action": action,
        "evidence_refs": list(request.evidence_refs),
        "surface_refs": list(request.surface_refs),
        "proof_receipt": {
            "head": before.head,
            "workspace": before.fingerprint,
            "evidence": evidence,
            "surface_refs": list(request.surface_refs),
        },
    }


def _decision_receipt(
    harness_dir: Path, task: dict, decision_id: str | None
) -> dict:
    from harness import source_access
    from harness.decision import DecisionError, load_decision

    if not decision_id:
        raise PlanMutationError("PLAN_DISPOSITION_INVALID")
    try:
        record = load_decision(harness_dir, decision_id)
        content = source_access.read_bytes(harness_dir / "decisions" / f"{decision_id}.yaml")
    except DecisionError as exc:
        if str(exc) == "DECISION_NOT_FOUND":
            raise PlanMutationError("PLAN_DISPOSITION_INVALID") from exc
        raise
    except OSError as exc:
        raise PlanMutationError("PLAN_DISPOSITION_INVALID") from exc
    if (
        record.get("task_id") != task.get("task", {}).get("id")
        or record.get("status") != "ACCEPTED"
    ):
        raise PlanMutationError("PLAN_DISPOSITION_INVALID")
    return {
        "decision_id": decision_id,
        "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
        "task_id": record["task_id"],
        "status": "ACCEPTED",
    }


def _lifecycle_transition(
    harness_dir: Path,
    task: dict,
    plan: dict,
    execution: dict,
    replay: ReplayResult,
    request: PlanMutationRequest,
    *,
    initial_snapshot=None,
) -> dict:
    item_id = request.item_id
    if not item_id or item_id not in {item["id"] for item in plan["items"]}:
        raise PlanMutationError("PLAN_SEQUENCE_INVALID")
    status = replay.items.get(item_id, {}).get("status", "PENDING")

    if request.action == "BEGIN":
        transition = {
            "item": item_id,
            "from": "PENDING",
            "to": "IN_PROGRESS",
            "action": "BEGIN",
        }
        if status == "IN_PROGRESS" and _exact_transition_retry(execution, request, transition):
            raise PlanMutationError("PLAN_EXACT_RETRY")
        if status != "PENDING" or replay.next_item != item_id or replay.active_item is not None:
            raise PlanMutationError("PLAN_SEQUENCE_INVALID")
        return transition

    if request.action == "BLOCK":
        reason = request.reason
        if not isinstance(reason, str) or not reason.strip():
            raise PlanMutationError("PLAN_DISPOSITION_INVALID")
        transition = {
            "item": item_id,
            "from": "IN_PROGRESS",
            "to": "BLOCKED",
            "action": "BLOCK",
            "reason": reason,
        }
        if status == "BLOCKED" and _exact_transition_retry(execution, request, transition):
            raise PlanMutationError("PLAN_EXACT_RETRY")
        if status != "IN_PROGRESS" or replay.active_item != item_id:
            raise PlanMutationError("PLAN_SEQUENCE_INVALID")
        return transition

    if request.action == "RESUME":
        transition = {
            "item": item_id,
            "from": "BLOCKED",
            "to": "IN_PROGRESS",
            "action": "RESUME",
        }
        if status == "IN_PROGRESS" and _exact_transition_retry(execution, request, transition):
            raise PlanMutationError("PLAN_EXACT_RETRY")
        if status != "BLOCKED" or replay.active_item != item_id:
            raise PlanMutationError("PLAN_SEQUENCE_INVALID")
        return transition

    if request.action == "RECONCILE":
        if request.disposition == "COMPLETE":
            transition = _proof_transition_payload(
                harness_dir,
                task,
                plan,
                replay,
                request,
                action="RECONCILE",
                initial_snapshot=initial_snapshot,
            )
        elif request.disposition in {"SKIPPED", "SUPERSEDED"}:
            if not isinstance(request.reason, str) or not request.reason.strip():
                raise PlanMutationError("PLAN_DISPOSITION_INVALID")
            receipt = _decision_receipt(harness_dir, task, request.decision_id)
            transition = {
                "item": item_id,
                "from": "IN_PROGRESS",
                "to": request.disposition,
                "action": "RECONCILE",
                "reason": request.reason,
                "decision_id": request.decision_id,
                "decision_receipt": receipt,
            }
            if request.disposition == "SUPERSEDED":
                plan_ids = {item["id"] for item in plan["items"]}
                if (
                    not request.replacements
                    or item_id in request.replacements
                    or any(value not in plan_ids for value in request.replacements)
                ):
                    raise PlanMutationError("PLAN_DISPOSITION_INVALID")
                transition["superseded_by"] = list(request.replacements)
        else:
            raise PlanMutationError("PLAN_DISPOSITION_INVALID")
        if status in {"COMPLETE", "SKIPPED", "SUPERSEDED"}:
            if _exact_transition_retry(execution, request, transition):
                raise PlanMutationError("PLAN_EXACT_RETRY")
            raise PlanMutationError("PLAN_DISPOSITION_INVALID")
        if status != "IN_PROGRESS" or replay.active_item != item_id:
            raise PlanMutationError("PLAN_SEQUENCE_INVALID")
        return transition

    if request.action == "REFRESH_PROOF":
        if status != "COMPLETE":
            raise PlanMutationError("PLAN_SEQUENCE_INVALID")
        transition = _proof_transition_payload(
            harness_dir,
            task,
            plan,
            replay,
            request,
            action="REFRESH_PROOF",
        )
        if _exact_transition_retry(execution, request, transition):
            raise PlanMutationError("PLAN_EXACT_RETRY")
        return transition

    raise PlanMutationError("PLAN_DISPOSITION_INVALID")


def _resolve_auto_request(
    harness_dir: Path,
    task: dict,
    plan: dict,
    execution: dict,
    replay: ReplayResult,
    request: PlanMutationRequest,
):
    if (
        request.action != "RECONCILE"
        or request.disposition is not None
        or request.reason is not None
        or request.evidence_refs
        or request.surface_refs
        or request.decision_id is not None
        or request.replacements
    ):
        raise PlanMutationError("PLAN_DISPOSITION_INVALID")
    item = next(
        (candidate for candidate in plan["items"] if candidate["id"] == request.item_id),
        None,
    )
    if item is None:
        raise PlanMutationError("PLAN_SEQUENCE_INVALID")
    status = replay.items.get(request.item_id, {}).get("status", "PENDING")
    exact_retry_candidate = bool(
        status == "COMPLETE"
        and execution["transitions"]
        and execution["transitions"][-1].get("item") == request.item_id
        and execution["transitions"][-1].get("action") == "RECONCILE"
    )
    if not (
        (status == "IN_PROGRESS" and replay.active_item == request.item_id)
        or exact_retry_candidate
    ):
        raise PlanMutationError("PLAN_SEQUENCE_INVALID")

    current = workspace_snapshot(harness_dir.parent)
    try:
        proof = plan_automation.derive_auto_proof(
            harness_dir,
            task,
            plan,
            item,
            head=current.head,
            workspace=current.fingerprint,
        )
    except plan_automation.PlanAutomationError as exc:
        raise PlanMutationError(exc.code) from exc
    return (
        PlanMutationRequest(
            action="RECONCILE",
            item_id=request.item_id,
            disposition="COMPLETE",
            evidence_refs=proof.evidence_refs,
            surface_refs=proof.surface_refs,
        ),
        current,
    )


def mutate_plan_execution(
    harness_dir: Path,
    task: dict,
    request: PlanMutationRequest,
) -> bool:
    """Apply one authorized task-level mutation under canonical Harness lock."""
    configuration = effective_plan_reconciliation(task)
    if not (
        configuration.get("enabled") is True
        and configuration.get("mode") == "task_and_final"
        and (task.get("risk") or {}).get("profile") == "STRICT"
    ):
        raise PlanMutationError("PLAN_TASK_LEVEL_DISABLED")
    if not _mutation_state_allowed(task, request.action):
        raise PlanMutationError("PLAN_MUTATION_NOT_ALLOWED")

    with telemetry_lock(harness_dir):
        plan, execution = load_plan_artifacts(harness_dir, optional=True)
        _raise_artifact_issue(plan, execution)
        assert plan is not None and execution is not None
        normalized = _normalize_mutation_request(plan, request)

        if normalized.action == "UPGRADE_EXECUTION":
            candidate = _upgrade_execution(plan, execution)
            if candidate is None:
                return False
        else:
            if execution["version"] != 2:
                raise PlanMutationError("PLAN_TASK_LEVEL_REQUIRED")
            replay = replay_plan_execution(plan, execution)
            if replay.issues:
                raise PlanMutationError("PLAN_SEQUENCE_INVALID")
            initial_snapshot = None
            if normalized.auto:
                normalized, initial_snapshot = _resolve_auto_request(
                    harness_dir,
                    task,
                    plan,
                    execution,
                    replay,
                    normalized,
                )
            try:
                transition = _lifecycle_transition(
                    harness_dir,
                    task,
                    plan,
                    execution,
                    replay,
                    normalized,
                    initial_snapshot=initial_snapshot,
                )
            except PlanMutationError as exc:
                if exc.code == "PLAN_EXACT_RETRY":
                    return False
                raise
            try:
                candidate = append_plan_transition(plan, execution, transition)
            except PlanExecutionError as exc:
                raise PlanMutationError("PLAN_SEQUENCE_INVALID") from exc
            if _supersession_issue(plan, candidate["items"]):
                raise PlanMutationError("PLAN_DISPOSITION_INVALID")

        try:
            validate(candidate, read_schema("plan-execution.schema.json"))
        except ValidationError as exc:
            raise PlanMutationError("PLAN_DISPOSITION_INVALID") from exc
        content = yaml.safe_dump(candidate, sort_keys=False).encode()
        atomic_write(harness_dir / "plan-execution.yaml", content)
        return True
