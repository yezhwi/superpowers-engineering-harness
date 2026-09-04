"""Control-plane command handlers for packaged ``src/harness`` runtime.

CLI parsing lives in :mod:`harness.cli`; deterministic policy lives in focused
Harness modules. Compatibility wrappers in ``scripts/`` re-export this source.
"""

import datetime
from dataclasses import replace

from harness import (
    benchmark,
    collect_evidence,
    complexity,
    decision,
    diagnosability,
    evidence_validator,
    harness_status,
    interface_contract,
    interface_review,
    quality_gate,
    review_outcome,
    risk,
    state_machine,
    telemetry,
    test_plan,
    transaction,
    workspace,
)
from harness import blockers as blocker_module
import json
import sys
import yaml
from pathlib import Path

from harness.paths import evidence_path
from harness.task_replacement import publish_replacement, replacement_workspace
from harness.templates import templates_dir


class HarnessStateError(Exception):
    """Invalid harness state (maps to exit code 2)."""


def load_task(harness_dir: Path) -> dict:
    import yaml

    path = harness_dir / "current-task.yaml"
    if not path.exists():
        raise HarnessStateError(f"missing {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise HarnessStateError(f"{path} is not a mapping")
    return data


def save_task(harness_dir: Path, task: dict) -> None:
    """Persist atomically: write temp file then rename."""
    import yaml

    path = harness_dir / "current-task.yaml"
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(
        yaml.safe_dump(task, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    tmp.replace(path)
    telemetry.update_telemetry(harness_dir, task)


def cmd_status(harness_dir: Path = Path(".harness")) -> int:
    return harness_status.main(["--harness-dir", str(harness_dir)])


def _decision_document(args) -> dict:
    options = []
    for value in args.option:
        option_id, separator, description = value.partition("=")
        if not separator or not option_id or not description:
            raise ValueError("DECISION_OPTION_INVALID")
        options.append({"id": option_id, "description": description})
    return {
        "topic": args.topic,
        "question": args.question,
        "context": args.context,
        "options": options,
        "recommendation": {
            "option": args.recommend,
            "reasons": args.reason,
            "tradeoffs": args.tradeoff,
        },
        "scope": args.scope,
        "constraints": args.constraint,
    }


def cmd_decision(args) -> int:
    """Route decision commands without leaking schema errors through CLI."""
    import yaml

    harness_dir = Path(".harness")
    try:
        if args.decision_command == "propose":
            record = decision.propose(harness_dir, _decision_document(args))
        elif args.decision_command == "accept":
            record = decision.load_decision(harness_dir, args.id)
            source = args.source or (
                "accepted_recommendation"
                if args.option == record["recommendation"]["option"]
                else "user_override"
            )
            record = decision.accept(harness_dir, args.id, args.option, source)
        elif args.decision_command == "reject":
            record = decision.reject(harness_dir, args.id, args.reason)
        elif args.decision_command == "supersede":
            _, record = decision.supersede(
                harness_dir, args.id, _decision_document(args)
            )
        elif args.decision_command == "list":
            print(yaml.safe_dump(decision.load_decisions(harness_dir), sort_keys=False))
            return 0
        elif args.decision_command == "show":
            print(
                yaml.safe_dump(
                    decision.load_decision(harness_dir, args.id), sort_keys=False
                )
            )
            return 0
        else:
            print("DECISION_COMMAND_INVALID", file=sys.stderr)
            return 2
    except (decision.DecisionError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"OK: {record['id']} {record['status']}")
    return 0


def cmd_interface(args) -> int:
    """Route external interface contract commands."""
    import yaml

    domain = interface_contract
    harness_dir = Path(".harness")
    try:
        if args.interface_command == "declare":
            record = domain.declare(
                harness_dir,
                {
                    "name": args.name,
                    "kind": args.kind,
                    "visibility": "external",
                    "consumers": args.consumer,
                    "inputs": {"description": args.input},
                    "outputs": {"description": args.output},
                    "errors": {"description": args.error},
                    "compatibility": {
                        "classification": args.compatibility,
                        "rationale": args.rationale,
                        "migration": args.migration,
                    },
                    "versioning": {"required": False, "strategy": None},
                    "observability": {"contract": "observability.yaml"},
                    "decision_refs": args.decision_ref,
                    "verification": [],
                },
            )
        elif args.interface_command == "verify":
            record = domain.verify(harness_dir, args.id, args.evidence)
        elif args.interface_command == "approve-breaking":
            record = domain.approve_breaking(harness_dir, args.id, args.reason)
        elif args.interface_command == "list":
            print(
                yaml.safe_dump(
                    domain.load_interface_contracts(harness_dir), sort_keys=False
                )
            )
            return 0
        elif args.interface_command == "show":
            print(
                yaml.safe_dump(
                    domain.load_interface_contract(harness_dir, args.id),
                    sort_keys=False,
                )
            )
            return 0
        else:
            print("INTERFACE_COMMAND_INVALID", file=sys.stderr)
            return 2
    except domain.InterfaceContractError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"OK: {record['id']} {record['status']}")
    return 0


def cmd_transition(target: str) -> int:
    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    current = task.get("state")
    profile = (task.get("risk") or {}).get("profile")
    if target == "GATING" and current != "REVIEWING":
        try:
            status, blockers = quality_gate.run_gate(harness_dir, allow_preflight=True)
        except Exception as exc:
            print(f"GATE_PREFLIGHT_INVALID: {exc}", file=sys.stderr)
            return 2
        if status != "PASS":
            print("GATE_PREFLIGHT_MISSING_EVIDENCE", file=sys.stderr)
            for blocker in blockers:
                print(f"- {blocker.code}: {blocker.message}", file=sys.stderr)
            return 1
    if target not in state_machine.STATES:
        print(f"unknown target state: {target!r}", file=sys.stderr)
        return 2
    # Reject malformed task identity/state before any business logic fires.
    try:
        quality_gate.validate_schema(
            task, "task.schema.json", harness_dir / "current-task.yaml"
        )
    except Exception as exc:
        print(f"INVALID_HARNESS_STATE: {exc}", file=sys.stderr)
        return 2
    if current == "CREATED" and target != "CLASSIFIED":
        print("TASK_CLASSIFICATION_REQUIRED", file=sys.stderr)
        return 1
    if current == "CLASSIFIED" and (
        (profile == "FAST" and target != "IMPLEMENTING")
        or (profile in {"STANDARD", "STRICT"} and target != "SPECIFYING")
    ):
        print("PROFILE_ENTRY_STATE_REQUIRED", file=sys.stderr)
        return 1
    if current == "BLOCKED":
        print("RESUME_REQUIRED: use harness resume", file=sys.stderr)
        return 1
    if current == "IMPLEMENTING" and target == "SPECIFYING":
        print("RISK_ESCALATION_REQUIRED: use harness task escalate", file=sys.stderr)
        return 1
    if current == "REPRODUCING" and target == "REVIEWING":
        try:
            fixed = [
                finding
                for finding in _findings(harness_dir)
                if finding.get("status") == "FIXED"
            ]
        except Exception:
            print("FINDING_STATE_INVALID", file=sys.stderr)
            return 2
        if fixed:
            print(
                f"FINDING_REVIEW_RESUME_REQUIRED: use harness finding resume-review {fixed[0]['id']}",
                file=sys.stderr,
            )
            return 1
    if current == "REVIEWING" and target in {"GATING", "VERIFYING", "REPRODUCING"}:
        print("REVIEW_OUTCOME_REQUIRED: use harness review outcome", file=sys.stderr)
        return 1
    if current == "CONVERGED" and target == "DONE":
        try:
            status, _ = quality_gate.run_gate(harness_dir, allow_converged=True)
        except quality_gate.InvalidHarnessState as exc:
            print(f"INVALID_HARNESS_STATE: {exc}", file=sys.stderr)
            return 2
        if status != "PASS":
            print("CURRENT_GATE_PASS_REQUIRED", file=sys.stderr)
            return 1
    if current == "PLANNED" and target == "IMPLEMENTING":
        decision_path = harness_dir / "evidence" / "minimal-implementation.yaml"
        try:
            import yaml

            decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
            complexity.validate_minimal_decision(decision)
        except Exception as exc:
            print(f"MINIMAL_IMPLEMENTATION_REQUIRED: {exc}", file=sys.stderr)
            return 1
        if profile in {"STANDARD", "STRICT"}:
            requirements_path = harness_dir / "requirements.yaml"
            invariants_path = harness_dir / "invariants.yaml"
            try:
                requirements = yaml.safe_load(
                    requirements_path.read_text(encoding="utf-8")
                )
                invariants = yaml.safe_load(invariants_path.read_text(encoding="utf-8"))
                quality_gate.validate_schema(
                    requirements, "requirement.schema.json", requirements_path
                )
                quality_gate.validate_schema(
                    invariants, "invariant.schema.json", invariants_path
                )
                issues = test_plan.validate_test_plan(requirements, invariants)
            except Exception as exc:
                print("TEST_PLAN_BLOCKED", file=sys.stderr)
                print(f"  TEST_PLAN_SCHEMA_INVALID: {exc}", file=sys.stderr)
                return 1
            if issues:
                print("TEST_PLAN_BLOCKED", file=sys.stderr)
                for issue in issues:
                    subject = issue.requirement_id or issue.invariant_id or "TEST_PLAN"
                    print(f"  {subject}: {issue.code}", file=sys.stderr)
                return 1
    if current == "VERIFYING" and target == "GATING" and profile != "FAST":
        print(
            "REVIEW_OUTCOME_REQUIRED: STANDARD/STRICT tasks must use review outcome",
            file=sys.stderr,
        )
        return 1
    if current == "VERIFYING" and target == "REVIEWING" and profile != "FAST":
        review_path = harness_dir / "evidence" / "complexity-review.json"
        try:
            review = json.loads(review_path.read_text(encoding="utf-8"))
            fingerprint = collect_evidence.workspace_fingerprint()
            evidence_validator.validate_evidence(
                review,
                current_head=quality_gate.git_head(),
                current_workspace=fingerprint,
                expected_success=True,
            )
        except Exception as exc:
            print(f"COMPLEXITY_REVIEW_REQUIRED: {exc}", file=sys.stderr)
            return 1
    if target == "VERIFYING" and profile != "FAST":
        _, impact = _impact()
        plan = impact["impact"]
        if not plan.get("required_tests"):
            print(
                "IMPACT_ANALYSIS_REQUIRED: impact.required_tests is empty",
                file=sys.stderr,
            )
            return 1
    if target not in state_machine.STATES or current not in state_machine.STATES:
        print(
            f"unknown state (current={current!r}, target={target!r})", file=sys.stderr
        )
        return 2
    try:
        state_machine.require_legal(current, target)
    except state_machine.InvalidTransition as exc:
        print(exc)
        return 1
    task["state"] = target
    save_task(harness_dir, task)
    print(f"OK: {current} -> {target}")
    return 0


def cmd_resume() -> int:
    """Recover BLOCKED task using highest-priority typed blocker only."""
    from harness.blockers import GateBlocker, select_recovery

    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    if task.get("state") != "BLOCKED":
        print("resume requires state BLOCKED", file=sys.stderr)
        return 1
    try:
        quality_gate.validate_schema(
            task, "task.schema.json", harness_dir / "current-task.yaml"
        )
        records = task.get("gate", {}).get("blocked_by", [])
        blockers = [GateBlocker(**record) for record in records]
        target = select_recovery(blockers)
        if target is None:
            raise ValueError("no deterministic recovery route")
        state_machine.require_legal("BLOCKED", target)
    except Exception as exc:
        print(f"INVALID_HARNESS_STATE: {exc}", file=sys.stderr)
        return 2
    task["state"] = target
    save_task(harness_dir, task)
    print(f"OK: BLOCKED -> {target}")
    return 0


def cmd_check_minimal(source: Path) -> int:
    import yaml

    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
        task = load_task(Path(".harness"))
        if not isinstance(document, dict):
            raise ValueError("decision file is not a mapping")
        if document.get("task") != task.get("task", {}).get("id"):
            raise ValueError("task mismatch")
        path = complexity.write_minimal_decision(Path(".harness"), document)
    except Exception as exc:
        print(f"INVALID MINIMAL IMPLEMENTATION: {exc}", file=sys.stderr)
        return 2
    print(f"minimal implementation evidence written: {path}")
    return 0


def cmd_review_outcome(outcome: str, reason_code: str, finding_ids: list[str]) -> int:
    """Persist a structured review outcome and take its sole legal route."""
    routes = {
        "PASS": "GATING",
        "VERIFICATION_GAP": "VERIFYING",
        "DEFECT": "REPRODUCING",
    }
    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    if task.get("state") != "REVIEWING":
        print("review outcome requires state REVIEWING", file=sys.stderr)
        return 1
    if not review_outcome.is_allowed(outcome, reason_code):
        print(f"INVALID_REVIEW_REASON_CODE: {reason_code}", file=sys.stderr)
        return 2
    if outcome == "DEFECT":
        findings = {finding.get("id"): finding for finding in _findings(harness_dir)}
        terminal = {"VERIFIED", "CLOSED", "REJECTED"}
        if not finding_ids or any(
            finding_id not in findings or findings[finding_id].get("status") in terminal
            for finding_id in finding_ids
        ):
            print("DEFECT_FINDING_REQUIRED", file=sys.stderr)
            return 2
    elif finding_ids:
        print("FINDING_NOT_ALLOWED_FOR_REVIEW_OUTCOME", file=sys.stderr)
        return 2
    target = routes[outcome]
    if target == "GATING":
        try:
            for name, schema in (
                ("current-task.yaml", "task.schema.json"),
                ("requirements.yaml", "requirement.schema.json"),
                ("invariants.yaml", "invariant.schema.json"),
            ):
                path = harness_dir / name
                quality_gate.validate_schema(
                    quality_gate._load_yaml(path), schema, path
                )
            status, blockers = quality_gate.run_gate(harness_dir, allow_preflight=True)
        except quality_gate.InvalidHarnessState as exc:
            print(f"GATE_PREFLIGHT_INVALID: {exc}", file=sys.stderr)
            return 2
        if status != "PASS":
            print("GATE_PREFLIGHT_MISSING_EVIDENCE", file=sys.stderr)
            for blocker in blockers:
                print(f"- {blocker.code}: {blocker.message}", file=sys.stderr)
            return 1
    task["review"] = {
        "outcome": outcome,
        "reason_code": reason_code,
        "message": "",
        "finding_ids": finding_ids,
    }
    task["state"] = target
    save_task(harness_dir, task)
    print(f"OK: REVIEWING -> {target}")
    return 0


def cmd_review_interface(source: Path, base_ref: str | None = None) -> int:
    harness_dir = Path(".harness")
    try:
        task = load_task(harness_dir)
        if task.get("state") != "REVIEWING":
            raise ValueError("review requires state REVIEWING")
        path = interface_review.write_review(
            harness_dir, source, task_id=task["task"]["id"]
        )
    except Exception as exc:
        print(f"INVALID INTERFACE REVIEW: {exc}", file=sys.stderr)
        return 2
    print(f"interface review written: {path}")
    return 0


def cmd_review_diagnosability(source: Path, base_ref: str | None = None) -> int:
    harness_dir = Path(".harness")
    try:
        task = load_task(harness_dir)
        if task.get("state") not in {"VERIFYING", "REVIEWING"}:
            raise ValueError("review requires state VERIFYING or REVIEWING")
        base = base_ref or task.get("git", {}).get("base_commit")
        if not base:
            raise ValueError("TASK_GIT_BASELINE_REQUIRED")
        review = diagnosability.load_review_input(source, task_id=task["task"]["id"])
        path = diagnosability.write_review(
            harness_dir,
            review,
            base_ref=base,
            task_type=task.get("task", {}).get("type"),
        )
    except Exception as exc:
        print(f"INVALID DIAGNOSABILITY REVIEW: {exc}", file=sys.stderr)
        return 2
    print(f"diagnosability review written: {path}")
    return 0


def cmd_review_complexity(source: Path, base_ref: str | None = None) -> int:
    import yaml

    try:
        review = yaml.safe_load(source.read_text(encoding="utf-8"))
        task = load_task(Path(".harness"))
        if not isinstance(review, dict) or review.get("task") != task.get(
            "task", {}
        ).get("id"):
            raise ValueError("task mismatch")
        base_ref = base_ref or task.get("git", {}).get("base_commit")
        if not base_ref:
            raise ValueError(
                "TASK_GIT_BASELINE_REQUIRED: provide --base or create a task with base_commit"
            )
        scope = workspace.review_scope(base_ref)
        if task.get("scope") is not None:
            files = workspace.project_task_scope(task, _impact()[1]["impact"])
            scope = replace(scope, files=files)
        claimed_scope = review.get("review_scope")
        if claimed_scope is not None and claimed_scope.get("files") != list(
            scope.files
        ):
            raise ValueError("COMPLEXITY_REVIEW_SCOPE_MISMATCH")
        paths = complexity.write_complexity_review(Path(".harness"), review, scope)
    except Exception as exc:
        print(f"INVALID COMPLEXITY REVIEW: {exc}", file=sys.stderr)
        return 2
    if "checks" not in review:
        print("COMPLEXITY_CHECKS_DEPRECATED", file=sys.stderr)
    print(f"complexity review written: {len(paths)} findings")
    return 0


def cmd_evidence_attach(evidence_type, command, scope, result_file):
    if result_file is None:
        print("EVIDENCE_ATTACH_INCOMPLETE", file=sys.stderr)
        return 2
    try:
        record = json.loads(result_file.read_text())
        required = {
            "command",
            "exit_code",
            "started_at",
            "finished_at",
            "git_head",
            "workspace_fingerprint",
            "stdout_digest",
            "stderr_digest",
        }
        provenance = record.get("provenance")
        provenance_required = {
            "kind",
            "command",
            "exit_code",
            "git_head",
            "workspace_fingerprint",
            "reference",
        }
        if (
            required - set(record)
            or record["command"] != command
            or not isinstance(provenance, dict)
            or provenance_required - set(provenance)
            or provenance["kind"] != "external"
            or any(
                provenance[field] != record[field]
                for field in ("command", "exit_code", "git_head", "workspace_fingerprint")
            )
        ):
            raise ValueError
        record.update(
            {
                "type": evidence_type,
                "timestamp": record["finished_at"],
                "commit": record["git_head"],
                "workspace_fingerprint_after": record["workspace_fingerprint"],
                "stdout_tail": record["stdout_digest"],
                "stderr_tail": record["stderr_digest"],
                "scope": scope,
            }
        )
        harness_dir = Path(".harness")
        quality_gate.validate_schema(
            record, "evidence.schema.json", result_file
        )
        current = workspace.snapshot()
        evidence_validator.validate_evidence(
            record,
            current_head=current.head,
            current_workspace=current.fingerprint,
            expected_success=True,
        )
        path = harness_dir / "evidence" / collect_evidence.evidence_filename(evidence_type)
        transaction.atomic_write(path, json.dumps(record).encode())
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        quality_gate.InvalidHarnessState,
        evidence_validator.EvidenceValidationError,
        workspace.WorkspaceError,
    ):
        print("EVIDENCE_ATTACH_INCOMPLETE", file=sys.stderr)
        return 2
    print("evidence attached")
    return 0


def cmd_evidence(
    evidence_type: str,
    command: str,
    finding_id=None,
    test_id=None,
    scope="related",
    covered_tests=(),
    covered_test_cases=(),
    phase=None,
    reuse_if_valid=False,
    budget_override_reason=None,
    budget_override_evidence=None,
    budget_override_hypothesis=None,
) -> int:
    args = ["--type", evidence_type, "--command", command, "--scope", scope]
    for covered_test in covered_tests:
        args.extend(["--covered-test", covered_test])
    for test_case in covered_test_cases:
        args.extend(["--covered-test-case", test_case])
    if phase is not None:
        args.extend(["--phase", phase])
    if finding_id is not None:
        args.extend(["--finding", finding_id, "--test", test_id])
    if reuse_if_valid:
        args.append("--reuse-if-valid")
    for flag, value in (
        ("--budget-override-reason", budget_override_reason),
        ("--budget-override-evidence", budget_override_evidence),
        ("--budget-override-hypothesis", budget_override_hypothesis),
    ):
        if value is not None:
            args.extend([flag, value])
    return collect_evidence.main(args)


def cmd_benchmark_corpus_validate(corpus: Path) -> int:
    try:
        rows = benchmark.validate_corpus(corpus)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"BENCHMARK_CORPUS_VALID: {len(rows)}")
    return 0


def cmd_benchmark_compare(fixtures: Path, baseline: Path, adaptive: Path) -> int:
    harness_dir = Path(".harness")
    try:
        report = benchmark.compare_benchmarks(fixtures, baseline, adaptive)
        import yaml

        fixture_rows = [
            yaml.safe_load(path.read_text()) for path in sorted(fixtures.glob("*.yaml"))
        ]
        report["acceptance"] = benchmark.evaluate_acceptance(report, fixture_rows)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    (harness_dir / "benchmark-report.json").write_text(json.dumps(report, indent=2))
    print(report["overall"])
    return 0


def cmd_benchmark_run(fixtures: Path) -> int:
    harness_dir = Path(".harness")
    try:
        report = benchmark.run_benchmarks(fixtures, harness_dir / "telemetry.json")
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    (harness_dir / "benchmark-report.json").write_text(json.dumps(report, indent=2))
    print("BENCHMARK_REPORT_WRITTEN")
    return 0


def cmd_telemetry_show() -> int:
    path = Path(".harness/telemetry.json")
    if not path.is_file():
        print("TELEMETRY_MISSING", file=sys.stderr)
        return 1
    print(path.read_text(), end="")
    return 0


def cmd_mr_describe() -> int:
    try:
        assessment = quality_gate.assess_gate(Path(".harness"), allow_preflight=True)
    except Exception as exc:
        print(f"MR_ASSESSMENT_INVALID: {exc}", file=sys.stderr)
        return 2
    quality = assessment.quality["status"]
    readiness = assessment.release_readiness["status"]
    print(f"Quality Gate: {quality}")
    print(f"MR Readiness: {'DRAFT ONLY' if readiness == 'DRAFT_ONLY' else readiness}")
    if readiness == "READY" and quality == "PASS":
        print("Ready for MR")
    return 0


def cmd_gate_preflight() -> int:
    """Run Gate assessment without changing task state."""
    try:
        assessment = quality_gate.assess_gate(Path(".harness"), allow_preflight=True)
    except Exception as exc:
        print(f"GATE_PREFLIGHT_INVALID: {exc}", file=sys.stderr)
        return 2
    status, blockers = assessment.status, assessment.blockers
    ready = status == "PASS" and assessment.release_readiness["status"] == "READY"
    print("READY: yes" if ready else "READY: no")
    commands = (
        yaml.safe_load((Path(".harness") / "gate.yaml").read_text())
        .get("gate", {})
        .get("verification_commands", {})
    )
    for blocker in blockers:
        print(f"- {blocker.code}: {blocker.message}")
        if blocker.source in commands:
            print(f"  command: {commands[blocker.source]}")
    return 0 if status == "PASS" else 1


def cmd_gate() -> int:
    """Evaluate Gate once and apply its deterministic convergence decision."""
    return _cmd_gate_convergence()


def _findings(harness_dir: Path) -> list:
    import yaml

    fdir = harness_dir / "findings"
    if not fdir.is_dir():
        return []
    out = []
    for path in sorted(fdir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise HarnessStateError("FINDING_STATE_INVALID") from exc
        if not isinstance(data, dict):
            raise HarnessStateError("FINDING_STATE_INVALID")
        out.append(data)
    return out


def cmd_finding_list() -> int:
    findings = _findings(Path(".harness"))
    if not findings:
        print("no findings")
        return 0
    print(f"{'ID':<10} {'SEVERITY':<9} {'STATUS':<12} TARGET")
    for f in findings:
        print(
            f"{f.get('id', '?'):<10} {f.get('severity', '?'):<9} "
            f"{f.get('status', '?'):<12} {f.get('target', '-')}"
        )
    return 0


def cmd_finding_show(finding_id: str) -> int:
    for f in _findings(Path(".harness")):
        if f.get("id") == finding_id:
            import yaml

            print(yaml.safe_dump(f, sort_keys=False, allow_unicode=True))
            return 0
    print(f"finding not found: {finding_id}", file=sys.stderr)
    return 1


def _cmd_gate_convergence() -> int:
    """Deterministic convergence decision (convergence skill v0.1 rules).

    PASS     (Gate status PASS)     -> GATING  -> CONVERGED
    ESCALATE (blocked, no budget)   -> via BLOCKED -> ESCALATED,
                                        reason MAX_ITERATIONS
    CONTINUE (blocked, budget left) -> GATING  -> BLOCKED, iteration += 1
    Non-GATING state or invalid harness -> exit 1.
    """
    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    current = task.get("state")

    if current != "GATING":
        print(
            f"converge requires state GATING, current is {current!r}", file=sys.stderr
        )
        return 1

    try:
        assessment = quality_gate.assess_gate(harness_dir)
    except quality_gate.InvalidHarnessState as exc:
        print(f"INVALID_HARNESS_STATE: {exc}", file=sys.stderr)
        return 1

    status, blockers = assessment.status, list(assessment.blockers)
    quality_gate.write_back(harness_dir, assessment)
    task = load_task(harness_dir)
    blocker_documents = [
        blocker_module.blocker_document(blocker) for blocker in blockers
    ]

    if status == "PASS":
        state_machine.require_legal("GATING", "CONVERGED")
        task["state"] = "CONVERGED"
        task.setdefault("gate", {}).update({"status": "PASS", "blocked_by": []})
        save_task(harness_dir, task)
        print("DECISION: CONVERGED (gate PASS)")
        return 0

    # Deterministic escalation beyond max_iterations: a finding that was
    # already VERIFIED (has verified_at) but is open again means the bug
    # regressed - fixing it again is unlikely to converge.
    def _reopened_regression() -> str | None:
        for f in _findings(harness_dir):
            if f.get("verified_at") and f.get("status") in (
                "PROPOSED",
                "REPRODUCING",
                "CONFIRMED",
                "FIXING",
                "FIXED",
            ):
                return f.get("id")
        return None

    iteration = int(task.get("iteration", 0))
    max_iterations = int(task.get("max_iterations", 5))
    reopened = _reopened_regression()

    if reopened:
        state_machine.require_legal("GATING", "BLOCKED")
        state_machine.require_legal("BLOCKED", "ESCALATED")
        task["state"] = "ESCALATED"
        task["iteration"] = iteration + 1
        task.setdefault("gate", {}).update(
            {"status": "BLOCKED", "blocked_by": blocker_documents}
        )
        save_task(harness_dir, task)
        print("DECISION: ESCALATED")
        print(f"REASON: REPEATED_REGRESSION ({reopened} was VERIFIED, now open again)")
        return 0

    if iteration >= max_iterations:
        state_machine.require_legal("GATING", "BLOCKED")
        state_machine.require_legal("BLOCKED", "ESCALATED")
        task["state"] = "ESCALATED"
        task["iteration"] = iteration + 1
        task.setdefault("gate", {}).update(
            {"status": "BLOCKED", "blocked_by": blocker_documents}
        )
        save_task(harness_dir, task)
        print("DECISION: ESCALATED")
        print("REASON: MAX_ITERATIONS")
        for blocker in blockers:
            print(f"  blocker: {blocker.message}")
        return 0

    state_machine.require_legal("GATING", "BLOCKED")
    task["state"] = "BLOCKED"
    task["iteration"] = iteration + 1
    task.setdefault("gate", {}).update(
        {"status": "BLOCKED", "blocked_by": blocker_documents}
    )
    save_task(harness_dir, task)
    print(f"DECISION: CONTINUE (iteration {task['iteration']} / {max_iterations})")
    for blocker in blockers:
        print(f"  blocker: {blocker.message}")
    return 0


def cmd_converge() -> int:
    """Deprecated compatibility command; Gate now owns convergence."""
    print("DEPRECATED: use harness gate", file=sys.stderr)
    return 2


def gate_pass(harness_dir: Path) -> bool:
    """True iff the gate passes for harness_dir (no side effects)."""
    head = quality_gate.git_head()
    try:
        status, _ = quality_gate.run_gate(harness_dir, head=head)
    except quality_gate.InvalidHarnessState:
        return False
    return status == "PASS"


_FINDING_TRANSITIONS = {
    "PROPOSED": {"REPRODUCING"},
    "REPRODUCING": {"CONFIRMED", "REJECTED"},
    "CONFIRMED": {"FIXING"},
    "FIXING": {"FIXED"},
    "FIXED": {"VERIFIED"},
    "VERIFIED": {"CLOSED"},
}


def cmd_finding_resume_review(fid):
    import yaml

    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    if task.get("state") != "REPRODUCING":
        print("FINDING_REVIEW_RESUME_STATE_INVALID", file=sys.stderr)
        return 1
    findings = [
        yaml.safe_load(path.read_text())
        for path in (harness_dir / "findings").glob("*.yaml")
    ]
    finding = next((item for item in findings if item.get("id") == fid), None)
    if not finding or finding.get("status") != "FIXED":
        print("FINDING_REVIEW_RESUME_INVALID", file=sys.stderr)
        return 1
    blocking = [
        item.get("id")
        for item in findings
        if item.get("status") in {"PROPOSED", "REPRODUCING", "CONFIRMED", "FIXING"}
    ]
    if blocking:
        print(
            "FINDING_REVIEW_RESUME_BLOCKED: blocking_findings: " + ", ".join(blocking),
            file=sys.stderr,
        )
        return 1
    state_machine.require_legal("REPRODUCING", "REVIEWING")
    task["state"] = "REVIEWING"
    save_task(harness_dir, task)
    print(f"OK: {fid} resume-review -> REVIEWING")
    return 0


def cmd_finding_transition(
    fid,
    target,
    evidence=None,
    test=None,
    attempt=None,
    reason=None,
    critical_related_approved=False,
):
    import yaml

    path = None
    finding = None
    for candidate in Path(".harness/findings").glob("*.yaml"):
        document = yaml.safe_load(candidate.read_text())
        if isinstance(document, dict) and document.get("id") == fid:
            path, finding = candidate, document
            break
    if not path:
        print(f"finding not found: {fid}", file=sys.stderr)
        return 1
    current = finding.get("status")
    if target not in _FINDING_TRANSITIONS.get(current, set()):
        print(f"INVALID FINDING TRANSITION: {current} -> {target}", file=sys.stderr)
        return 1

    def proof(reference, succeeds, test_id=None):
        if not reference:
            raise ValueError("missing --evidence")
        evidence_file = evidence_path(Path(".harness"), reference)
        record = json.loads(evidence_file.read_text())
        try:
            evidence_validator.validate_evidence(
                record,
                current_head=quality_gate.git_head(),
                current_workspace=collect_evidence.workspace_fingerprint(),
                expected_success=succeeds,
                finding_id=fid if test_id else None,
                test_id=test_id,
            )
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        return evidence_file.name

    try:
        if target == "REPRODUCING":
            if not attempt:
                raise ValueError("REPRODUCING requires --attempt")
            finding.setdefault("attempts", []).append(attempt)
        elif target == "CONFIRMED":
            finding["confirmed_at"] = datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat()
            if finding.get("category") != "diagnosability":
                if not test:
                    raise ValueError("CONFIRMED requires --test")
                evidence = proof(evidence, False, test)
                finding["test"] = test
                finding["regression_test"] = {"path": test, "red_evidence": evidence}
        elif target == "FIXED" and finding.get("category") != "diagnosability":
            evidence = proof(evidence, True, finding["regression_test"]["path"])
            finding["regression_test"]["green_evidence"] = evidence
        elif target == "VERIFIED":
            if not evidence:
                raise ValueError("missing --evidence")
            evidence_file = evidence_path(Path(".harness"), evidence)
            record = json.loads(evidence_file.read_text())
            head = quality_gate.git_head()
            current_workspace = collect_evidence.workspace_fingerprint()
            impact_path = Path(".harness/impact.yaml")
            impact = (
                yaml.safe_load(impact_path.read_text()) if impact_path.exists() else {}
            )
            if critical_related_approved:
                if (
                    finding.get("severity") != "critical"
                    or record.get("scope") != "related"
                ):
                    raise ValueError(
                        "--critical-related-approved requires critical related evidence"
                    )
                finding["closure"] = {
                    "mode": "related",
                    "critical_related_approved": True,
                    "approved_at": datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(),
                    "source": "user",
                }
            if finding.get("category") == "diagnosability":
                diagnosability.validate_compliance_closure(
                    finding,
                    record,
                    current_head=head,
                    current_workspace=current_workspace,
                )
            else:
                evidence_validator.validate_finding_closure_evidence(
                    finding,
                    record,
                    impact,
                    current_head=head,
                    current_workspace=current_workspace,
                )
            finding["evidence"] = evidence_file.name
            finding["verified_at"] = datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat()
        elif target == "REJECTED":
            if not reason or not finding.get("attempts"):
                raise ValueError("REJECTED requires attempts and --reason")
            finding["rejection_reason"] = reason
    except (
        ValueError,
        OSError,
        json.JSONDecodeError,
        evidence_validator.EvidenceValidationError,
    ) as exc:
        print(f"INVALID FINDING PROOF: {exc}", file=sys.stderr)
        return 2
    finding["status"] = target
    transaction.atomic_write(path, yaml.safe_dump(finding, sort_keys=False).encode())
    print(f"OK: {fid} {current} -> {target}")
    return 0


def cmd_task_migrate_id(task_id: str) -> int:
    import re

    if not re.fullmatch(r"TASK-[0-9]+", task_id):
        print("INVALID TASK ID: must match TASK-[0-9]+", file=sys.stderr)
        return 2
    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    task.setdefault("task", {})["id"] = task_id
    save_task(harness_dir, task)
    print(f"OK: task id -> {task_id}")
    return 0


def cmd_task_classify(level: str, dimensions: dict[str, str]) -> int:
    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    if task.get("state") != "CREATED":
        print("task classify requires state CREATED", file=sys.stderr)
        return 1
    try:
        profile = risk.classify(level, dimensions)
        state_machine.require_legal("CREATED", "CLASSIFIED")
        user_changes = workspace.snapshot().changed_paths
        task["scope"] = {"owned_paths": [], "protected_user_paths": list(user_changes)}
        head = workspace.git_head()
        task["git"] = {
            "base_ref": "HEAD",
            "base_commit": head,
            "head_at_start": head,
            "head": head,
        }
        task["risk"] = {
            "level": level,
            "profile": profile,
            "dimensions": dimensions,
            "escalation_history": [],
            "user_changes": {
                "paths": list(user_changes),
                "fingerprint": workspace.protected_paths_fingerprint(user_changes),
            },
        }
    except Exception as exc:
        print(f"RISK_CLASSIFICATION_INVALID: {exc}", file=sys.stderr)
        return 2
    task["state"] = "CLASSIFIED"
    save_task(harness_dir, task)
    print(f"OK: classified {level}/{profile}")
    return 0


def cmd_task_escalate(level: str, reason: str) -> int:
    import shutil

    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    risk_record = task.get("risk")
    if not isinstance(risk_record, dict) or not reason.strip():
        print("RISK_ESCALATION_INVALID", file=sys.stderr)
        return 2
    try:
        risk.validate_escalation(risk_record["level"], level)
    except Exception as exc:
        print(f"RISK_ESCALATION_INVALID: {exc}", file=sys.stderr)
        return 2
    fast_task = risk_record.get("profile") == "FAST"
    if fast_task and task.get("state") not in {
        "CLASSIFIED",
        "IMPLEMENTING",
        "VERIFYING",
    }:
        print("RISK_ESCALATION_REQUIRES_RESTART", file=sys.stderr)
        return 1
    try:
        staged = replacement_workspace(harness_dir)
        staged_task = load_task(staged)
        staged_risk = staged_task["risk"]
        restarting_contract = fast_task and staged_task["state"] in {
            "IMPLEMENTING",
            "VERIFYING",
        }
        if restarting_contract:
            state_machine.require_legal("IMPLEMENTING", "SPECIFYING")
            for name in ("requirements.yaml", "invariants.yaml", "observability.yaml"):
                shutil.copy2(templates_dir() / name, staged / name)
            (staged / "evidence" / "minimal-implementation.yaml").unlink(
                missing_ok=True
            )
            staged_task["state"] = "SPECIFYING"
        staged_risk["escalation_history"].append(
            {"from": staged_risk["level"], "to": level, "reason": reason}
        )
        staged_risk["level"] = level
        staged_risk["profile"] = risk.PROFILES[level]
        save_task(staged, staged_task)
        publish_replacement(harness_dir, staged)
    except Exception as exc:
        if "staged" in locals():
            shutil.rmtree(staged, ignore_errors=True)
        print(f"RISK_ESCALATION_INVALID: {exc}", file=sys.stderr)
        return 2
    print(f"OK: escalated to {level}/{risk.PROFILES[level]}")
    return 0


def _verify_record(kind: str, rid: str, ref: str) -> int:
    import yaml

    harness_dir = Path(".harness")
    filename = "requirements.yaml" if kind == "requirement" else "invariants.yaml"
    path = harness_dir / filename
    document = yaml.safe_load(path.read_text())
    key = "requirements" if kind == "requirement" else "invariants"
    record = next(
        (item for item in document.get(key, []) if item.get("id") == rid), None
    )
    if not record:
        print(f"{kind} not found: {rid}", file=sys.stderr)
        return 1
    try:
        evidence_file = evidence_path(harness_dir, ref)
        evidence = json.loads(evidence_file.read_text())
        evidence_validator.validate_evidence(
            evidence,
            current_head=quality_gate.git_head(),
            current_workspace=collect_evidence.workspace_fingerprint(),
            expected_success=True,
        )
    except Exception as exc:
        print(f"INVALID EVIDENCE: {exc}", file=sys.stderr)
        return 2
    field = "evidence" if kind == "requirement" else "verification"
    record.setdefault(field, [])
    if evidence_file.name not in record[field]:
        record[field].append(evidence_file.name)
    record["status"] = "verified"
    transaction.atomic_write(path, yaml.safe_dump(document, sort_keys=False).encode())
    print(f"OK: {rid} verified")
    return 0


def cmd_requirement_verify(rid, ref):
    return _verify_record("requirement", rid, ref)


def cmd_invariant_verify(rid, ref):
    return _verify_record("invariant", rid, ref)


def initialize_task_git(task: dict, head: str) -> None:
    """Set replacement-task immutable baseline and current HEAD together."""
    task["git"] = {"base_commit": head, "head": head}


def task_git_head_or_error() -> str:
    """Resolve required task baseline before any replacement-task mutation."""
    return workspace.git_head()


def cmd_task_new(task_id: str, title: str = "") -> int:
    import re
    import shutil

    if not re.fullmatch(r"TASK-[0-9]+", task_id):
        print("INVALID TASK ID", file=sys.stderr)
        return 2
    harness_dir = Path(".harness")
    old = load_task(harness_dir)
    if old.get("state") not in {"DONE", "ESCALATED"}:
        print("task new requires DONE or ESCALATED task", file=sys.stderr)
        return 1
    try:
        head = task_git_head_or_error()
    except workspace.WorkspaceError as exc:
        print(f"TASK_GIT_BASELINE_REQUIRED: {exc}", file=sys.stderr)
        return 2
    try:
        staged = replacement_workspace(harness_dir)
        archive = (
            staged
            / "history"
            / f"{old['task']['id']}-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
        )
        archive.mkdir(parents=True, exist_ok=False)
        for name in (
            "current-task.yaml",
            "requirements.yaml",
            "invariants.yaml",
            "gate.yaml",
            "impact.yaml",
            "observability.yaml",
            "findings",
            "evidence",
        ):
            source = staged / name
            if source.exists():
                shutil.copytree(
                    source, archive / name
                ) if source.is_dir() else shutil.copy2(source, archive / name)
        for name in (
            "current-task.yaml",
            "requirements.yaml",
            "invariants.yaml",
            "gate.yaml",
            "impact.yaml",
            "observability.yaml",
        ):
            shutil.copy2(templates_dir() / name, staged / name)
        for name in ("findings", "evidence"):
            shutil.rmtree(staged / name, ignore_errors=True)
            (staged / name).mkdir()
        task = load_task(staged)
        task["task"]["id"] = task_id
        task["task"]["title"] = title
        task["timestamps"]["created_at"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        initialize_task_git(task, head)
        save_task(staged, task)
        publish_replacement(harness_dir, staged)
    except Exception as exc:
        print(f"TASK_REPLACEMENT_FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"OK: archived task, created {task_id}")
    return 0


def cmd_task_recover(task_id: str, title: str, reason: str) -> int:
    """Atomically archive active task and publish replacement task."""
    import re
    import shutil
    import yaml

    if not re.fullmatch(r"TASK-[0-9]+", task_id):
        print("INVALID TASK ID", file=sys.stderr)
        return 2
    if not reason.strip():
        print("RECOVERY_REASON_REQUIRED", file=sys.stderr)
        return 2
    harness_dir = Path(".harness")
    old = load_task(harness_dir)
    if old.get("state") in {"DONE", "ESCALATED"}:
        print("task recover requires active task", file=sys.stderr)
        return 1
    old_id = old.get("task", {}).get("id") or "UNKNOWN"
    try:
        head = task_git_head_or_error()
    except workspace.WorkspaceError as exc:
        print(f"TASK_GIT_BASELINE_REQUIRED: {exc}", file=sys.stderr)
        return 2
    try:
        staged = replacement_workspace(harness_dir)
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        archive = staged / "history" / f"{old_id}-{timestamp}"
        archive.mkdir(parents=True, exist_ok=False)
        for name in (
            "current-task.yaml",
            "requirements.yaml",
            "invariants.yaml",
            "gate.yaml",
            "impact.yaml",
            "observability.yaml",
            "findings",
            "evidence",
        ):
            source = staged / name
            if source.exists():
                shutil.copytree(
                    source, archive / name
                ) if source.is_dir() else shutil.copy2(source, archive / name)
        audit = {
            "recovered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "reason": reason,
            "previous_task_id": old_id,
            "previous_state": old.get("state"),
            "replacement_task_id": task_id,
        }
        (archive / "recovery.yaml").write_text(yaml.safe_dump(audit, sort_keys=False))
        for name in (
            "current-task.yaml",
            "requirements.yaml",
            "invariants.yaml",
            "gate.yaml",
            "impact.yaml",
            "observability.yaml",
        ):
            shutil.copy2(templates_dir() / name, staged / name)
        for name in ("findings", "evidence"):
            shutil.rmtree(staged / name, ignore_errors=True)
            (staged / name).mkdir()
        task = load_task(staged)
        task["task"]["id"] = task_id
        task["task"]["title"] = title
        task["timestamps"]["created_at"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        initialize_task_git(task, head)
        save_task(staged, task)
        publish_replacement(harness_dir, staged)
    except Exception as exc:
        print(f"TASK_REPLACEMENT_FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"OK: recovered {old_id}, created {task_id}")
    return 0


AUTHORIZATION_ACTIONS = (
    "commit",
    "full_suite",
    "push",
    "create_mr",
    "ready_mr",
    "merge",
    "deploy",
)


def _authorization_record(granted: bool = False) -> dict:
    return {"granted": granted, "granted_at": None, "source": None}


def authorization_granted(task: dict, action: str) -> bool:
    """Check one action only; legacy authorization applies only to full suite."""
    normalized = (task.get("authorizations") or {}).get(action)
    if isinstance(normalized, dict):
        return normalized.get("granted") is True
    if action == "full_suite":
        return (task.get("authorization") or {}).get("full_suite", {}).get(
            "granted"
        ) is True
    return False


def cmd_authorize(action: str, granted: bool) -> int:
    if action not in AUTHORIZATION_ACTIONS:
        print("AUTHORIZATION_ACTION_INVALID", file=sys.stderr)
        return 2
    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    records = task.setdefault("authorizations", {})
    for name in AUTHORIZATION_ACTIONS:
        records.setdefault(name, _authorization_record())
    records[action] = {
        "granted": granted,
        "granted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": "user",
    }
    save_task(harness_dir, task)
    return 0


def cmd_authorize_full_suite(granted: bool) -> int:
    """Backward-compatible internal API."""
    return cmd_authorize("full_suite", granted)


def _impact():
    import yaml

    path = Path(".harness/impact.yaml")
    default = {
        "impact": {
            "changed": [],
            "direct_dependents": [],
            "contracts": [],
            "interfaces": [],
            "risks": [],
            "required_tests": [],
            "full_suite": {"recommended": False, "reason": None},
        }
    }
    return path, yaml.safe_load(path.read_text()) if path.exists() else default


def cmd_impact(action, value=None, reason=None, args=None):
    import yaml

    path, document = _impact()
    impact = document["impact"]
    if action == "show":
        print(yaml.safe_dump(document, sort_keys=False))
        return 0
    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    if "scope" not in task:
        task["scope"] = {
            "owned_paths": list(impact.get("changed", [])),
            "protected_user_paths": [],
        }
        save_task(harness_dir, task)
    scope = task["scope"]
    if action == "scope":
        effective = workspace.project_task_scope(task, impact)
        print(
            yaml.safe_dump(
                {
                    "owned_paths": scope.get("owned_paths", []),
                    "protected_user_paths": scope.get("protected_user_paths", []),
                    "effective_scope": list(effective),
                },
                sort_keys=False,
            )
        )
        return 0
    if action in {"adopt-path", "ignore-user-path"}:
        owned, protected = scope["owned_paths"], scope["protected_user_paths"]
        if action == "adopt-path":
            if value not in owned:
                owned.append(value)
            if value in protected:
                protected.remove(value)
        elif value not in owned and value not in protected:
            protected.append(value)
        save_task(harness_dir, task)
        return 0
    if action == "add-interface":
        if (
            task.get("risk", {}).get("profile") == "FAST"
            and args.visibility == "external"
        ):
            print("PUBLIC_INTERFACE_RISK_ESCALATION_REQUIRED", file=sys.stderr)
            return 1
        impact.setdefault("interfaces", []).append(
            {
                "id": value,
                "kind": args.kind,
                "visibility": args.visibility,
                "consumers": args.consumer,
                "compatibility": args.compatibility,
                "affected_contracts": [],
                "contract_id": args.contract_id,
            }
        )
        transaction.atomic_write(
            path, yaml.safe_dump(document, sort_keys=False).encode()
        )
        return 0
    key = {
        "add-change": "changed",
        "add-test": "required_tests",
        "add-dependent": "direct_dependents",
        "add-contract": "contracts",
        "add-risk": "risks",
    }.get(action)
    if key:
        if value not in impact[key]:
            impact[key].append(value)
        if action == "add-change":
            if value not in scope["owned_paths"]:
                scope["owned_paths"].append(value)
            if value in scope["protected_user_paths"]:
                scope["protected_user_paths"].remove(value)
            save_task(harness_dir, task)
    elif action == "require-full-suite":
        impact["full_suite"] = {"recommended": True, "reason": reason}
    transaction.atomic_write(path, yaml.safe_dump(document, sort_keys=False).encode())
    return 0
