#!/usr/bin/env python3
"""quality_gate.py -- deterministic quality gate (Milestone 2 core).

Reads .harness/{current-task.yaml, requirements.yaml, invariants.yaml,
gate.yaml}, findings/*.yaml, evidence/*.json and git HEAD.
All checks are deterministic Python logic -- no LLM judgement.

Exit codes:
  0 = PASS
  1 = BLOCKED (blockers listed on stdout)
  2 = INVALID_HARNESS_STATE
"""

import argparse
from dataclasses import dataclass
import json
import sys
from pathlib import Path

import yaml
from jsonschema import ValidationError, validate

from .blockers import GateBlocker, RECOVERY_POLICY, blocker_document
from .evidence_validator import EvidenceValidationError, validate_evidence
from .paths import EvidenceReferenceError, evidence_path
from .state_machine import STATES
from .test_plan import validate_test_coverage, validate_test_plan
from .risk_boundaries import RiskBoundaryPolicyError, business_paths, load_boundaries, required_level
from .workspace import (
    WorkspaceError, changed_paths_since, git_head as workspace_head,
    protected_paths_fingerprint, snapshot,
)

# Finding statuses that must block the gate. Terminal/healthy:
# VERIFIED, CLOSED, REJECTED. FIXED (test green, regression pending)
# still blocks - full regression evidence does not exist yet.
OPEN_FINDING_STATUSES = {
    "PROPOSED", "REPRODUCING", "CONFIRMED", "FIXING", "FIXED",
}


class InvalidHarnessState(Exception):
    pass


from importlib import resources

SCHEMAS_DIR = resources.files("harness").joinpath("schemas")


def validate_schema(document: object, schema_name: str, source: Path) -> None:
    """Fail closed when any persisted harness document violates its schema."""
    schema_path = SCHEMAS_DIR / schema_name
    try:
        schema = json.loads(schema_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidHarnessState(f"cannot load {schema_path}: {exc}") from exc
    try:
        validate(document, schema)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "$"
        raise InvalidHarnessState(
            f"{source} fails {schema_name} at {location}: {exc.message}"
        ) from exc


def _load_yaml(path: Path):
    if not path.exists():
        raise InvalidHarnessState(f"missing {path}")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise InvalidHarnessState(f"bad YAML in {path}: {exc}")
    if not isinstance(data, dict):
        raise InvalidHarnessState(f"{path} is not a mapping")
    return data


def git_head() -> str:
    try:
        return workspace_head()
    except WorkspaceError as exc:
        raise InvalidHarnessState(str(exc)) from exc


def load_evidence(evidence_dir: Path) -> list[dict]:
    """Return every evidence record; same-type records must not overwrite proof."""
    evidence = []
    if not evidence_dir.is_dir():
        return evidence
    for path in sorted(evidence_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise InvalidHarnessState(f"bad JSON in {path}: {exc}")
        validate_schema(data, "evidence.schema.json", path)
        evidence.append(data)
    return evidence


def finding_schema_name(finding: dict) -> str:
    """Return canonical schema for one persisted finding discriminator."""
    category = finding.get("category")
    if category == "diagnosability":
        return "diagnosability-finding.schema.json"
    if category == "complexity":
        return "complexity-finding.schema.json"
    if category is None and finding.get("kind") in {
        "failure_scenario", "requirement_violation", "invariant_violation",
    }:
        return "adversarial-finding.schema.json"
    raise InvalidHarnessState("FINDING_SCHEMA_UNKNOWN")


def load_findings(findings_dir: Path) -> list:
    findings = []
    if not findings_dir.is_dir():
        return findings
    for path in sorted(findings_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            raise InvalidHarnessState(f"{path} is not a mapping")
        validate_schema(data, finding_schema_name(data), path)
        findings.append(data)
    return findings


def fast_verification_policy(harness_dir: Path) -> dict[str, str]:
    try:
        policy = _load_yaml(harness_dir / "gate.yaml").get("gate", {}).get("fast", {}).get("verification")
    except InvalidHarnessState:
        policy = None
    if policy is None:
        return {"build": "required"}
    if not isinstance(policy, dict) or any(value not in {"required", "optional"} for value in policy.values()):
        raise InvalidHarnessState("FAST verification policy invalid")
    return policy


def run_fast_gate(task: dict, harness_dir: Path, head: str,
                  current_workspace: str) -> tuple[str, list[GateBlocker]]:
    """Run Q1 Light Gate without STANDARD/STRICT ceremony artifacts."""
    risk = task.get("risk") or {}
    user_changes = risk.get("user_changes") or {}
    paths = tuple(user_changes.get("paths") or [])
    blockers: list[GateBlocker] = []

    def block(code: str, message: str) -> None:
        blockers.append(GateBlocker(
            code, "verification", message, recover_to=RECOVERY_POLICY.get(code)
        ))

    try:
        protected = protected_paths_fingerprint(paths)
    except WorkspaceError as exc:
        raise InvalidHarnessState(f"cannot verify user changes: {exc}") from exc
    if protected != user_changes.get("fingerprint"):
        block("FAST_USER_CHANGE_MODIFIED", "pre-existing user changes were modified")

    try:
        paths = business_paths(changed_paths_since(task["git"]["base_commit"]))
    except (KeyError, WorkspaceError) as exc:
        raise InvalidHarnessState(f"cannot revalidate FAST risk: {exc}") from exc
    if paths:
        try:
            level = required_level(paths, load_boundaries(harness_dir / "risk-boundaries.yaml"))
        except RiskBoundaryPolicyError:
            block("RISK_REVALIDATION_POLICY_MISSING", "FAST business changes require risk-boundaries policy")
        else:
            current_level = risk.get("level")
            if level and ("Q1", "Q2", "Q3").index(current_level) < ("Q1", "Q2", "Q3").index(level):
                block("RISK_ESCALATION_REQUIRED", f"FAST changes require escalation to {level}")

    for evidence_type, policy in fast_verification_policy(harness_dir).items():
        if policy != "required":
            continue
        path = harness_dir / "evidence" / f"{evidence_type.replace('_', '-')}.json"
        try:
            validate_evidence(json.loads(path.read_text()), current_head=head,
                              current_workspace=current_workspace, expected_success=True)
        except (OSError, json.JSONDecodeError, EvidenceValidationError) as exc:
            block("FAST_REPOSITORY_VERIFICATION_MISSING",
                  f"FAST {evidence_type.replace('_', '-')} evidence invalid: {exc}")

    for phase, expected_success, require_current in (
        ("red", False, False), ("green", True, True),
    ):
        path = harness_dir / "evidence" / f"fast-{phase}-unit-test.json"
        try:
            record = json.loads(path.read_text())
            validate_evidence(
                record, current_head=head, current_workspace=current_workspace,
                expected_success=expected_success,
                require_current_workspace=require_current,
            )
        except (OSError, json.JSONDecodeError, EvidenceValidationError) as exc:
            block("FAST_REGRESSION_EVIDENCE_MISSING",
                  f"FAST {phase} regression evidence invalid: {exc}")
    return ("PASS" if not blockers else "BLOCKED"), blockers


def _evaluate_gate(harness_dir: Path, head: str | None = None,
                   allow_converged: bool = False, allow_preflight: bool = False) -> tuple[str, list]:
    """Returns (status, blockers). status in {'PASS','BLOCKED'}.
    Raises InvalidHarnessState."""
    task = _load_yaml(harness_dir / "current-task.yaml")
    validate_schema(task, "task.schema.json", harness_dir / "current-task.yaml")

    state = task.get("state")
    if state not in STATES:
        raise InvalidHarnessState(f"unknown task state {state!r}")

    # Single legal path: REVIEWING -> GATING -> quality gate.
    if state != "GATING" and not (allow_converged and state == "CONVERGED") and not allow_preflight:
        raise InvalidHarnessState(
            f"state {state} does not allow gate execution (must be GATING)"
        )

    risk = task.get("risk")
    if isinstance(risk, dict):
        expected_profile = {"Q1": "FAST", "Q2": "STANDARD", "Q3": "STRICT"}.get(
            risk.get("level")
        )
        if expected_profile is None or risk.get("profile") != expected_profile:
            raise InvalidHarnessState("RISK_PROFILE_INVALID")

    head = head if head is not None else git_head()
    try:
        current_workspace = snapshot().fingerprint
    except WorkspaceError as exc:
        raise InvalidHarnessState(f"cannot fingerprint workspace: {exc}") from exc
    gate_doc = _load_yaml(harness_dir / "gate.yaml")
    validate_schema(gate_doc, "gate.schema.json", harness_dir / "gate.yaml")
    if (task.get("risk") or {}).get("profile") == "FAST":
        return run_fast_gate(task, harness_dir, head, current_workspace)

    requirements_doc = _load_yaml(harness_dir / "requirements.yaml")
    invariants_doc = _load_yaml(harness_dir / "invariants.yaml")
    validate_schema(requirements_doc, "requirement.schema.json", harness_dir / "requirements.yaml")
    validate_schema(invariants_doc, "invariant.schema.json", harness_dir / "invariants.yaml")
    gate_cfg = gate_doc["gate"]
    evidence = load_evidence(harness_dir / "evidence")
    findings = load_findings(harness_dir / "findings")
    impact_path = harness_dir / "impact.yaml"
    impact = _load_yaml(impact_path) if impact_path.exists() else {}
    # HEAD alone misses uncommitted edits. Shared snapshot excludes harness
    # runtime files, so evidence writes do not invalidate business proof.
    # Terminal/near-terminal findings require real proof records, not only
    # schema-shaped strings. Fail closed before open-finding policy runs.
    def finding_proof(finding, ref, expected_success, label, test_id=None):
        try:
            path = evidence_path(harness_dir, ref)
            record = json.loads(path.read_text())
            validate_evidence(record, current_head=head, current_workspace=current_workspace,
                              expected_success=expected_success,
                              require_current_workspace=expected_success,
                              finding_id=finding["id"] if test_id else None,
                              test_id=test_id)
        except (OSError, json.JSONDecodeError, EvidenceValidationError, EvidenceReferenceError) as exc:
            raise InvalidHarnessState(f"{finding['id']} {label} evidence invalid: {exc}") from exc
    for finding in findings:
        state = finding["status"]
        if finding.get("category") == "diagnosability":
            if state in {"VERIFIED", "CLOSED"}:
                try:
                    record = json.loads(evidence_path(harness_dir, finding["evidence"]).read_text())
                    from .diagnosability import validate_compliance_closure
                    validate_compliance_closure(
                        finding, record, current_head=head,
                        current_workspace=current_workspace,
                    )
                except (OSError, json.JSONDecodeError, ValueError, EvidenceReferenceError) as exc:
                    raise InvalidHarnessState(
                        f"{finding['id']} compliance evidence invalid: {exc}"
                    ) from exc
            continue
        if state in {"CONFIRMED", "FIXING", "FIXED", "VERIFIED", "CLOSED"}:
            finding_proof(finding, finding["regression_test"]["red_evidence"], False, "red", finding["regression_test"]["path"])
        if state in {"FIXED", "VERIFIED", "CLOSED"}:
            finding_proof(finding, finding["regression_test"]["green_evidence"], True, "green", finding["regression_test"]["path"])
        if state in {"VERIFIED", "CLOSED"}:
            try:
                record = json.loads(evidence_path(harness_dir, finding["evidence"]).read_text())
                from .evidence_validator import validate_finding_closure_evidence
                validate_finding_closure_evidence(
                    finding, record, impact, current_head=head,
                    current_workspace=current_workspace,
                )
            except (OSError, json.JSONDecodeError, EvidenceValidationError, EvidenceReferenceError) as exc:
                raise InvalidHarnessState(
                    f"{finding['id']} full regression evidence invalid: {exc}"
                ) from exc

    blockers: list[GateBlocker] = []

    def block(code: str, category: str, message: str, **identity) -> None:
        blockers.append(GateBlocker(
            code, category, message, recover_to=RECOVERY_POLICY.get(code), **identity
        ))

    from .diagnosability import gate_blockers
    blockers.extend(gate_blockers(harness_dir, task, head=head, workspace=current_workspace))

    # 1. Requirements: priority=must must be verified WITH fresh evidence.
    # A self-declared status=verified carries no weight on its own: each
    # verified must-requirement needs >=1 evidence ref resolving to an
    # evidence file that exists, ran successfully, and matches HEAD.
    req_cfg = gate_cfg.get("requirements", {})
    if req_cfg.get("must_verified", True):
        evidence_dir = harness_dir / "evidence"
        for req in requirements_doc.get("requirements", []):
            if req.get("priority") != "must":
                continue
            if req.get("status") != "verified":
                block("REQUIREMENT_UNVERIFIED", "verification", f"{req.get('id')} not verified", requirement_id=req.get("id"))
                continue
            refs = req.get("evidence") or []
            if not refs:
                block("EVIDENCE_MISSING", "verification", f"{req.get('id')} verified without evidence", requirement_id=req.get("id"))
                continue
            for ref in refs:
                name = ref if isinstance(ref, str) else                     (ref or {}).get("ref", "")
                if not name:
                    block("EVIDENCE_MISSING", "verification", f"{req.get('id')} has an empty evidence ref", requirement_id=req.get("id"))
                    continue
                try:
                    path = evidence_path(harness_dir, name)
                except EvidenceReferenceError:
                    block("EVIDENCE_MISSING", "verification", f"{req.get('id')} evidence reference invalid", requirement_id=req.get("id"))
                    continue
                if not path.is_file():
                    block("EVIDENCE_MISSING", "verification", f"{req.get('id')} evidence missing: {path.name}", source=path.name, requirement_id=req.get("id"))
                    continue
                try:
                    ev = json.loads(path.read_text())
                except json.JSONDecodeError as exc:
                    raise InvalidHarnessState(
                        f"bad JSON in {path}: {exc}")
                try:
                    validate_evidence(ev, current_head=head, current_workspace=current_workspace,
                                      expected_success=True)
                except EvidenceValidationError as exc:
                    block(str(exc).split(":", 1)[0], "verification", f"{req.get('id')} evidence {path.name} invalid: {exc}", source=path.name, requirement_id=req.get("id"))

    # 2. Invariants: violated blocks; unproven blocks for critical/major.
    # pending == not proven == BLOCKED. Only proven-safe (verified)
    # invariants may pass the gate. Minor invariants are configurable via
    # gate.invariants.minor_verified (default false).
    inv_cfg = gate_cfg.get("invariants", {})
    minor_verified = bool(inv_cfg.get("minor_verified", False))
    for inv in invariants_doc.get("invariants", []):
        status = inv.get("status")
        severity = inv.get("severity")
        iid = inv.get("id")
        if status == "violated":
            block("INVARIANT_VIOLATED", "implementation", f"{iid} violated", invariant_id=iid)
        elif status != "verified":
            if severity in ("critical", "major"):
                block("INVARIANT_UNVERIFIED", "verification", f"{iid} not verified (pending {severity} invariant is not proven)", invariant_id=iid)
            elif severity == "minor" and minor_verified:
                block("INVARIANT_UNVERIFIED", "verification", f"{iid} not verified", invariant_id=iid)
        elif severity in ("critical", "major") or minor_verified:
            refs = inv.get("verification") or []
            if not refs:
                block("EVIDENCE_MISSING", "verification", f"{iid} verified without verification evidence", invariant_id=iid)
            for ref in refs:
                name = ref if isinstance(ref, str) else (ref or {}).get("ref", "")
                try:
                    path = evidence_path(harness_dir, name)
                except EvidenceReferenceError:
                    block("EVIDENCE_MISSING", "verification", f"{iid} verification evidence reference invalid", invariant_id=iid)
                    continue
                try:
                    ev = json.loads(path.read_text())
                except (OSError, json.JSONDecodeError):
                    block("EVIDENCE_MISSING", "verification", f"{iid} verification evidence missing: {name}", source=name, invariant_id=iid)
                    continue
                try:
                    validate_evidence(ev, current_head=head, current_workspace=current_workspace,
                                      expected_success=True)
                except EvidenceValidationError as exc:
                    block(str(exc).split(":", 1)[0], "verification", f"{iid} verification evidence {name} invalid: {exc}", source=name, invariant_id=iid)

    # 3. Required verification evidence exists, exit_code==0, fresh HEAD.
    ver_cfg = gate_cfg.get("verification", {})
    for vtype, policy in ver_cfg.items():
        if policy != "required":
            continue
        matching = [record for record in evidence if record.get("type") == vtype]
        label = vtype.replace("_", "-")
        if not matching:
            block("EVIDENCE_MISSING", "verification", f"missing {label} evidence", source=vtype)
            continue
        for ev in matching:
            try:
                validate_evidence(ev, current_head=head, current_workspace=current_workspace,
                                  expected_success=True)
                break
            except EvidenceValidationError as exc:
                last_error = exc
        else:
            block(str(last_error).split(":", 1)[0], "verification", f"{label} evidence invalid: {last_error}", source=vtype)

    # 3b. Test Plan: all non-FAST tasks must remain complete at Final Gate.
    for issue in validate_test_plan(requirements_doc, invariants_doc):
        block("TEST_PLAN_INCOMPLETE", "implementation", issue.message,
              requirement_id=issue.requirement_id, invariant_id=issue.invariant_id)

    # 3c. Test Plan: every automated binding needs fresh successful evidence.
    def evidence_is_fresh(record):
        try:
            validate_evidence(record, current_head=head, current_workspace=current_workspace,
                              expected_success=True)
            return True
        except EvidenceValidationError:
            return False

    for issue in validate_test_coverage(
            requirements_doc, invariants_doc, evidence, evidence_is_fresh):
        if issue.code == "TEST_BINDING_MISSING":
            block(issue.code, "implementation", issue.message,
                  requirement_id=issue.requirement_id, invariant_id=issue.invariant_id)
        else:
            block(issue.code, "verification", issue.message,
                  requirement_id=issue.requirement_id, invariant_id=issue.invariant_id)

    # 4. Complexity: required review evidence and configured open severities.
    complexity_cfg = gate_cfg.get("complexity", {})
    if complexity_cfg.get("required", False):
        review_path = harness_dir / "evidence" / "complexity-review.json"
        try:
            review = json.loads(review_path.read_text())
            validate_schema(review, "evidence.schema.json", review_path)
        except (OSError, json.JSONDecodeError, InvalidHarnessState):
            block("COMPLEXITY_REVIEW_MISSING", "verification", "missing complexity-review evidence", source="complexity-review")
        else:
            try:
                validate_evidence(review, current_head=head, current_workspace=current_workspace,
                                  expected_success=True)
            except EvidenceValidationError as exc:
                block(str(exc).split(":", 1)[0], "verification", f"complexity-review evidence invalid: {exc}", source="complexity-review")
        blocking = set(complexity_cfg.get("blocking", ["high"]))
        for finding in findings:
            if (finding.get("id", "").startswith("CPLX-")
                    and finding.get("status") == "open"
                    and finding.get("severity") in blocking):
                block("IMPLEMENTATION_INCOMPLETE", "implementation", f"{finding['severity'].title()} complexity finding {finding['id']} is open", finding_id=finding["id"])

    # 5. Findings: open critical/major counts, regression debt.
    find_cfg = gate_cfg.get("findings", {})
    critical_allowed = int(find_cfg.get("critical_allowed", 0))
    major_allowed = int(find_cfg.get("major_allowed", 0))

    def is_open(f):
        return f.get("status") in OPEN_FINDING_STATUSES

    open_critical = [f for f in findings
                     if is_open(f) and f.get("severity") == "critical"]
    open_major = [f for f in findings
                  if is_open(f) and f.get("severity") == "major"]
    for f in open_critical[critical_allowed:]:
        block("FINDING_OPEN", "defect", f"Critical finding {f['id']} is open", finding_id=f["id"])
    for f in open_major[major_allowed:]:
        block("FINDING_OPEN", "defect", f"Major finding {f['id']} is open", finding_id=f["id"])

    # Confirmed findings must carry a regression test (LAW 4).
    confirmed = [
        finding for finding in findings
        if finding.get("status") == "CONFIRMED"
        and finding.get("category") != "diagnosability"
    ]
    regression_cfg = gate_cfg.get("regression", {})
    without_test_allowed = int(
        regression_cfg.get("confirmed_finding_without_test", 0))
    no_test = [f for f in confirmed
               if not (f.get("regression_test") or {}).get("path")]
    for f in no_test[without_test_allowed:]:
        block("IMPLEMENTATION_INCOMPLETE", "implementation", f"Confirmed finding {f['id']} has no regression test", finding_id=f["id"])

    status = "PASS" if not blockers else "BLOCKED"
    return status, blockers


@dataclass(frozen=True)
class GateAssessment:
    status: str
    blockers: tuple[GateBlocker, ...]
    quality: dict[str, str]
    release_readiness: dict[str, list[str] | str]


def assess_gate(harness_dir: Path, head: str | None = None,
                allow_converged: bool = False, allow_preflight: bool = False) -> GateAssessment:
    """Evaluate current Harness state without persisting a Gate result."""
    status, blockers = _evaluate_gate(
        harness_dir, head=head, allow_converged=allow_converged,
        allow_preflight=allow_preflight,
    )
    release = _load_yaml(harness_dir / "gate.yaml").get("gate", {}).get("release", {})
    authorized = bool(((_load_yaml(harness_dir / "current-task.yaml").get("authorizations") or {})
                       .get("full_suite", {}).get("granted")))
    readiness = (
        {"status": "NOT_READY", "reasons": ["quality_gate_blocked"]}
        if status != "PASS" else
        {"status": "DRAFT_ONLY", "reasons": ["full_suite_required_but_not_authorized"]}
        if release.get("full_suite_required") and not authorized else
        {"status": "READY", "reasons": []}
    )
    return GateAssessment(status, tuple(blockers),
                          {"status": "PASS" if status == "PASS" else "BLOCKED"}, readiness)


def run_gate(harness_dir: Path, head: str | None = None,
             allow_converged: bool = False, allow_preflight: bool = False) -> tuple[str, list]:
    assessment = assess_gate(
        harness_dir, head=head, allow_converged=allow_converged,
        allow_preflight=allow_preflight,
    )
    return assessment.status, list(assessment.blockers)


def write_back(harness_dir: Path, assessment: GateAssessment):
    """Persist already-computed assessment; never evaluate Gate a second time."""
    path = harness_dir / "current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task.setdefault("gate", {})
    task["gate"]["status"] = assessment.status
    task["gate"]["blocked_by"] = [blocker_document(blocker) for blocker in assessment.blockers]
    task["gate"]["quality"] = assessment.quality
    task["gate"]["release_readiness"] = assessment.release_readiness
    task.setdefault("git", {})["head"] = git_head()
    path.write_text(yaml.safe_dump(task, sort_keys=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deterministic quality gate")
    parser.add_argument("--harness-dir", default=".harness")
    args = parser.parse_args(argv)

    harness_dir = Path(args.harness_dir)
    try:
        assessment = assess_gate(harness_dir)
        status, blockers = assessment.status, list(assessment.blockers)
        write_back(harness_dir, assessment)
    except InvalidHarnessState as exc:
        print(f"INVALID_HARNESS_STATE: {exc}", file=sys.stderr)
        return 2

    if status == "PASS":
        print("QUALITY GATE: PASS")
        return 0

    print("QUALITY GATE: BLOCKED")
    print()
    print("Blocking:")
    for blocker in blockers:
        print(f"- {blocker.message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
