"""Canonical implementation-plan fingerprinting and reconciliation helpers."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from jsonschema import ValidationError, validate

from .blockers import GateBlocker
from .collect_evidence import command_covers_test, record_covers_test
from .evidence_validator import EvidenceStatus, project_evidence
from .paths import EvidenceReferenceError, evidence_path
from .schema_resources import read_schema
from .workspace import changed_paths_since, protected_paths_fingerprint

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


@dataclass(frozen=True)
class PlanIssue:
    code: str
    message: str


def _load_yaml(path: Path, schema_name: str) -> tuple[dict | None, PlanIssue | None]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        validate(document, read_schema(schema_name))
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        raise PlanArtifactError(f"PLAN_SCHEMA_INVALID: {path}") from exc
    if schema_name == "plan.schema.json":
        item_ids = [item["id"] for item in document["items"]]
        if len(item_ids) != len(set(item_ids)):
            raise PlanArtifactError("PLAN_ITEM_ID_DUPLICATE")
    return document, None


def validate_plan_initialization(harness_dir: Path) -> list[PlanIssue]:
    """Validate artifacts needed before enabled task implementation begins."""
    plan_path = harness_dir / "plan.yaml"
    execution_path = harness_dir / "plan-execution.yaml"
    if not plan_path.is_file() or not execution_path.is_file():
        return [PlanIssue("PLAN_REQUIRED", "enabled task requires plan artifacts")]
    plan, issue = _load_yaml(plan_path, "plan.schema.json")
    if issue:
        return [issue]
    execution, issue = _load_yaml(execution_path, "plan-execution.schema.json")
    if issue:
        return [issue]
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


def _qualified_cases(harness_dir: Path) -> dict[str, set[str]]:
    cases: dict[str, set[str]] = {}
    for filename, key in (("requirements.yaml", "requirements"), ("invariants.yaml", "invariants")):
        try:
            document = yaml.safe_load((harness_dir / filename).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        for record in document.get(key, []):
            cases[record.get("id")] = {
                case.get("id"): case
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


def _supersession_issue(plan: dict, execution: dict) -> tuple[str, str] | None:
    plan_ids = {item["id"] for item in plan["items"]}
    graph: dict[str, list[str]] = {}
    for item_id, record in execution["items"].items():
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
    """Return final-plan blockers for enabled tasks after regular Gate checks."""
    issues = validate_plan_initialization(harness_dir)
    if issues:
        return [_blocker(issue) for issue in issues]

    plan, _ = _load_yaml(harness_dir / "plan.yaml", "plan.schema.json")
    execution, _ = _load_yaml(
        harness_dir / "plan-execution.yaml", "plan-execution.schema.json"
    )
    if supersession := _supersession_issue(plan, execution):
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
    protected_changed = bool(protected) and (
        protected_paths_fingerprint(tuple(sorted(protected)))
        != user_changes.get("fingerprint")
    )
    changed_surfaces = (
        set(changed_paths_since(task.get("git", {}).get("base_commit", "HEAD")))
        if any(item.get("surfaces", []) for item in plan["items"])
        else set()
    )
    if not protected_changed:
        changed_surfaces -= protected

    blockers: list[GateBlocker] = []
    for item in plan["items"]:
        item_id = item["id"]
        record = execution["items"].get(item_id)
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
            record["status"] == "COMPLETE"
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
            record["status"] == "COMPLETE"
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
            record["status"] == "COMPLETE"
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
            record["status"] == "COMPLETE"
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
            record["status"] == "COMPLETE"
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
            record["status"] == "COMPLETE"
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
