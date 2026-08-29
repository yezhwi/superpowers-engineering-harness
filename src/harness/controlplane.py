"""Control-plane subcommands (guide v0.1 section 34).

Thin wrappers over the deterministic scripts in <repo>/scripts. Logic is
imported from the scripts directory -- never re-implemented here, so the
CLI and the scripts can never diverge.
"""

import datetime
import importlib
import json
import sys
from pathlib import Path

from harness.templates import templates_dir


class HarnessStateError(Exception):
    """Invalid harness state (maps to exit code 2)."""


def _load(name: str):
    """Load bundled runtime module without repository-layout discovery."""
    return importlib.import_module(f"harness.{name}")


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
    tmp.write_text(yaml.safe_dump(task, sort_keys=False, allow_unicode=True),
                   encoding="utf-8")
    tmp.replace(path)
    _load("telemetry").update_telemetry(harness_dir, task)


def cmd_status() -> int:
    return _load("harness_status").main([])


def cmd_transition(target: str) -> int:
    state_machine = _load("state_machine")
    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    current = task.get("state")
    profile = (task.get("risk") or {}).get("profile")
    if current == "CLASSIFIED" and ((profile == "FAST" and target != "IMPLEMENTING") or (profile in {"STANDARD", "STRICT"} and target != "SPECIFYING")):
        print("PROFILE_ENTRY_STATE_REQUIRED", file=sys.stderr)
        return 1
    if current == "BLOCKED" and target == "VERIFYING":
        print("RESUME_REQUIRED: use harness resume", file=sys.stderr)
        return 1
    if current == "REVIEWING" and target in {"GATING", "VERIFYING", "REPRODUCING"}:
        print("REVIEW_OUTCOME_REQUIRED: use harness review outcome", file=sys.stderr)
        return 1
    # Reject malformed task identity/state before it can advance toward Gate.
    try:
        _load("quality_gate").validate_schema(
            task, "task.schema.json", harness_dir / "current-task.yaml")
    except Exception as exc:
        print(f"INVALID_HARNESS_STATE: {exc}", file=sys.stderr)
        return 2
    if current == "CONVERGED" and target == "DONE":
        quality_gate = _load("quality_gate")
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
            _load("complexity").validate_minimal_decision(decision)
        except Exception as exc:
            print(f"MINIMAL_IMPLEMENTATION_REQUIRED: {exc}", file=sys.stderr)
            return 1
        if profile in {"STANDARD", "STRICT"}:
            requirements_path = harness_dir / "requirements.yaml"
            invariants_path = harness_dir / "invariants.yaml"
            try:
                requirements = yaml.safe_load(requirements_path.read_text(encoding="utf-8"))
                invariants = yaml.safe_load(invariants_path.read_text(encoding="utf-8"))
                quality_gate = _load("quality_gate")
                quality_gate.validate_schema(requirements, "requirement.schema.json", requirements_path)
                quality_gate.validate_schema(invariants, "invariant.schema.json", invariants_path)
                issues = _load("test_plan").validate_test_plan(requirements, invariants)
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
        print("REVIEW_OUTCOME_REQUIRED: STANDARD/STRICT tasks must use review outcome", file=sys.stderr)
        return 1
    if current == "VERIFYING" and target == "REVIEWING" and profile != "FAST":
        review_path = harness_dir / "evidence" / "complexity-review.json"
        try:
            review = json.loads(review_path.read_text(encoding="utf-8"))
            quality_gate = _load("quality_gate")
            fingerprint = _load("collect_evidence").workspace_fingerprint()
            _load("evidence_validator").validate_evidence(
                review, current_head=quality_gate.git_head(), current_workspace=fingerprint,
                expected_success=True)
        except Exception as exc:
            print(f"COMPLEXITY_REVIEW_REQUIRED: {exc}", file=sys.stderr)
            return 1
    if target == "VERIFYING" and profile != "FAST":
        _, impact = _impact()
        plan = impact["impact"]
        if not plan.get("required_tests"):
            print("IMPACT_ANALYSIS_REQUIRED: impact.required_tests is empty", file=sys.stderr)
            return 1
    if target not in state_machine.STATES or current not in \
            state_machine.STATES:
        print(f"unknown state (current={current!r}, target={target!r})",
              file=sys.stderr)
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
        _load("quality_gate").validate_schema(
            task, "task.schema.json", harness_dir / "current-task.yaml")
        records = task.get("gate", {}).get("blocked_by", [])
        blockers = [GateBlocker(**record) for record in records]
        target = select_recovery(blockers)
        if target is None:
            raise ValueError("no deterministic recovery route")
        _load("state_machine").require_legal("BLOCKED", target)
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
        path = _load("complexity").write_minimal_decision(Path(".harness"), document)
    except Exception as exc:
        print(f"INVALID MINIMAL IMPLEMENTATION: {exc}", file=sys.stderr)
        return 2
    print(f"minimal implementation evidence written: {path}")
    return 0


def cmd_review_outcome(outcome: str, reason_code: str, finding_ids: list[str]) -> int:
    """Persist a structured review outcome and take its sole legal route."""
    routes = {"PASS": "GATING", "VERIFICATION_GAP": "VERIFYING", "DEFECT": "REPRODUCING"}
    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    if task.get("state") != "REVIEWING":
        print("review outcome requires state REVIEWING", file=sys.stderr)
        return 1
    if not _load("review_outcome").is_allowed(outcome, reason_code):
        print(f"INVALID_REVIEW_REASON_CODE: {reason_code}", file=sys.stderr)
        return 2
    if outcome == "DEFECT":
        findings = {finding.get("id"): finding for finding in _findings(harness_dir)}
        terminal = {"VERIFIED", "CLOSED", "REJECTED"}
        if (not finding_ids or any(
                finding_id not in findings or findings[finding_id].get("status") in terminal
                for finding_id in finding_ids)):
            print("DEFECT_FINDING_REQUIRED", file=sys.stderr)
            return 2
    elif finding_ids:
        print("FINDING_NOT_ALLOWED_FOR_REVIEW_OUTCOME", file=sys.stderr)
        return 2
    target = routes[outcome]
    task["review"] = {"outcome": outcome, "reason_code": reason_code,
                      "message": "", "finding_ids": finding_ids}
    task["state"] = target
    save_task(harness_dir, task)
    print(f"OK: REVIEWING -> {target}")
    return 0


def cmd_review_diagnosability(source: Path, base_ref: str | None = None) -> int:
    harness_dir = Path(".harness")
    try:
        task = load_task(harness_dir)
        if task.get("state") != "REVIEWING":
            raise ValueError("review requires state REVIEWING")
        base = base_ref or task.get("git", {}).get("base_commit")
        if not base:
            raise ValueError("TASK_GIT_BASELINE_REQUIRED")
        review = _load("diagnosability").load_review_input(source, task_id=task["task"]["id"])
        path = _load("diagnosability").write_review(harness_dir, review, base_ref=base)
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
        if not isinstance(review, dict) or review.get("task") != task.get("task", {}).get("id"):
            raise ValueError("task mismatch")
        base_ref = base_ref or task.get("git", {}).get("base_commit")
        if not base_ref:
            raise ValueError("TASK_GIT_BASELINE_REQUIRED: provide --base or create a task with base_commit")
        scope = _load("workspace").review_scope(base_ref)
        claimed_scope = review.get("review_scope")
        if claimed_scope is not None and claimed_scope.get("files") != list(scope.files):
            raise ValueError("COMPLEXITY_REVIEW_SCOPE_MISMATCH")
        paths = _load("complexity").write_complexity_review(Path(".harness"), review, scope)
    except Exception as exc:
        print(f"INVALID COMPLEXITY REVIEW: {exc}", file=sys.stderr)
        return 2
    print(f"complexity review written: {len(paths)} findings")
    return 0


def cmd_evidence(evidence_type: str, command: str, finding_id=None, test_id=None,
                 scope="related", covered_tests=(), covered_test_cases=(), phase=None,
                 reuse_if_valid=False, budget_override_reason=None,
                 budget_override_evidence=None, budget_override_hypothesis=None) -> int:
    collect_evidence = _load("collect_evidence")
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
    for flag, value in (("--budget-override-reason", budget_override_reason), ("--budget-override-evidence", budget_override_evidence), ("--budget-override-hypothesis", budget_override_hypothesis)):
        if value is not None:
            args.extend([flag, value])
    return collect_evidence.main(args)


def cmd_benchmark_corpus_validate(corpus: Path) -> int:
    try:
        rows = _load("benchmark").validate_corpus(corpus)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"BENCHMARK_CORPUS_VALID: {len(rows)}")
    return 0


def cmd_benchmark_compare(fixtures: Path, baseline: Path, adaptive: Path) -> int:
    harness_dir = Path(".harness")
    try:
        benchmark = _load("benchmark")
        report = benchmark.compare_benchmarks(fixtures, baseline, adaptive)
        import yaml
        fixture_rows = [yaml.safe_load(path.read_text()) for path in sorted(fixtures.glob("*.yaml"))]
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
        report = _load("benchmark").run_benchmarks(fixtures, harness_dir / "telemetry.json")
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
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            out.append(data)
    return out


def cmd_finding_list() -> int:
    findings = _findings(Path(".harness"))
    if not findings:
        print("no findings")
        return 0
    print(f"{'ID':<10} {'SEVERITY':<9} {'STATUS':<12} TARGET")
    for f in findings:
        print(f"{f.get('id', '?'):<10} {f.get('severity', '?'):<9} "
              f"{f.get('status', '?'):<12} {f.get('target', '-')}")
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

    PASS     (gate exit 0)          -> GATING  -> CONVERGED
    ESCALATE (blocked, no budget)   -> via BLOCKED -> ESCALATED,
                                        reason MAX_ITERATIONS
    CONTINUE (blocked, budget left) -> GATING  -> BLOCKED, iteration += 1
    Non-GATING state or invalid harness -> exit 1.
    """
    quality_gate = _load("quality_gate")
    state_machine = _load("state_machine")
    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    current = task.get("state")

    if current != "GATING":
        print(f"converge requires state GATING, current is {current!r}",
              file=sys.stderr)
        return 1

    try:
        status, blockers = quality_gate.run_gate(harness_dir)
    except quality_gate.InvalidHarnessState as exc:
        print(f"INVALID_HARNESS_STATE: {exc}", file=sys.stderr)
        return 1

    quality_gate.write_back(harness_dir, status, blockers)
    task = load_task(harness_dir)
    blocker_documents = [_load("blockers").blocker_document(blocker) for blocker in blockers]

    if status == "PASS":
        state_machine.require_legal("GATING", "CONVERGED")
        task["state"] = "CONVERGED"
        task["gate"] = {"status": "PASS", "blocked_by": []}
        save_task(harness_dir, task)
        print("DECISION: CONVERGED (gate PASS)")
        return 0

    # Deterministic escalation beyond max_iterations: a finding that was
    # already VERIFIED (has verified_at) but is open again means the bug
    # regressed - fixing it again is unlikely to converge.
    def _reopened_regression() -> str | None:
        for f in _findings(harness_dir):
            if f.get("verified_at") and f.get("status") in (
                    "PROPOSED", "REPRODUCING", "CONFIRMED", "FIXING",
                    "FIXED"):
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
        task["gate"] = {"status": "BLOCKED", "blocked_by": blocker_documents}
        save_task(harness_dir, task)
        print("DECISION: ESCALATED")
        print(f"REASON: REPEATED_REGRESSION ({reopened} was VERIFIED, "
              "now open again)")
        return 0

    if iteration >= max_iterations:
        state_machine.require_legal("GATING", "BLOCKED")
        state_machine.require_legal("BLOCKED", "ESCALATED")
        task["state"] = "ESCALATED"
        task["iteration"] = iteration + 1
        task["gate"] = {"status": "BLOCKED", "blocked_by": blocker_documents}
        save_task(harness_dir, task)
        print("DECISION: ESCALATED")
        print("REASON: MAX_ITERATIONS")
        for blocker in blockers:
            print(f"  blocker: {blocker.message}")
        return 0

    state_machine.require_legal("GATING", "BLOCKED")
    task["state"] = "BLOCKED"
    task["iteration"] = iteration + 1
    task["gate"] = {"status": "BLOCKED", "blocked_by": blocker_documents}
    save_task(harness_dir, task)
    print(f"DECISION: CONTINUE (iteration {task['iteration']} /"
      f" {max_iterations})")
    for blocker in blockers:
        print(f"  blocker: {blocker.message}")
    return 0


def cmd_converge() -> int:
    """Deprecated compatibility command; Gate now owns convergence."""
    print("DEPRECATED: use harness gate", file=sys.stderr)
    return 2


def gate_pass(harness_dir: Path) -> bool:
    """True iff the gate passes for harness_dir (no side effects)."""
    quality_gate = _load("quality_gate")
    head = quality_gate.git_head()
    try:
        status, _ = quality_gate.run_gate(harness_dir, head=head)
    except quality_gate.InvalidHarnessState:
        return False
    return status == "PASS"

_FINDING_TRANSITIONS={"PROPOSED":{"REPRODUCING"},"REPRODUCING":{"CONFIRMED","REJECTED"},"CONFIRMED":{"FIXING"},"FIXING":{"FIXED"},"FIXED":{"VERIFIED"},"VERIFIED":{"CLOSED"}}
def cmd_finding_transition(fid,target,evidence=None,test=None,attempt=None,reason=None,critical_related_approved=False):
 import yaml,datetime,json
 path=None; finding=None
 for p in Path('.harness/findings').glob('*.yaml'):
  x=yaml.safe_load(p.read_text())
  if isinstance(x,dict) and x.get('id')==fid: path,finding=p,x; break
 if not path: print(f'finding not found: {fid}',file=sys.stderr); return 1
 current=finding.get('status')
 if target not in _FINDING_TRANSITIONS.get(current,set()): print(f'INVALID FINDING TRANSITION: {current} -> {target}',file=sys.stderr); return 1
 def proof(ref,ok,test_id=None):
  if not ref: raise ValueError('missing --evidence')
  p=Path('.harness/evidence')/(ref if ref.endswith('.json') else ref+'.json')
  d=json.loads(p.read_text()); head=_load('quality_gate').git_head()
  workspace=_load('collect_evidence').workspace_fingerprint()
  try: _load('evidence_validator').validate_evidence(d,current_head=head,current_workspace=workspace,expected_success=ok,finding_id=fid if test_id else None,test_id=test_id)
  except Exception as exc: raise ValueError(str(exc)) from exc
 try:
  if target=='REPRODUCING':
   if not attempt: raise ValueError('REPRODUCING requires --attempt')
   finding.setdefault('attempts',[]).append(attempt)
  elif target=='CONFIRMED':
   if finding.get('category')=='diagnosability': finding['confirmed_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
   else:
    if not test: raise ValueError('CONFIRMED requires --test')
    proof(evidence,False,test); finding['test']=test; finding['regression_test']={'path':test,'red_evidence':evidence}; finding['confirmed_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
  elif target=='FIXED':
   if finding.get('category')!='diagnosability': proof(evidence,True,finding['regression_test']['path']); finding['regression_test']['green_evidence']=evidence
  elif target=='VERIFIED':
   if not evidence: raise ValueError('missing --evidence')
   p=Path('.harness/evidence')/(evidence if evidence.endswith('.json') else evidence+'.json')
   d=json.loads(p.read_text()); head=_load('quality_gate').git_head(); workspace=_load('collect_evidence').workspace_fingerprint()
   impact_path=Path('.harness/impact.yaml'); impact=yaml.safe_load(impact_path.read_text()) if impact_path.exists() else {}
   if critical_related_approved:
    if finding.get('severity') != 'critical' or d.get('scope') != 'related': raise ValueError('--critical-related-approved requires critical related evidence')
    finding['closure']={'mode':'related','critical_related_approved':True,'approved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source':'user'}
   if finding.get('category')=='diagnosability': _load('diagnosability').validate_compliance_closure(finding,d,current_head=head,current_workspace=workspace)
   else: _load('evidence_validator').validate_finding_closure_evidence(finding,d,impact,current_head=head,current_workspace=workspace)
   finding['evidence']=evidence; finding['verified_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
  elif target=='REJECTED':
   if not reason or not finding.get('attempts'): raise ValueError('REJECTED requires attempts and --reason')
   finding['rejection_reason']=reason
 except (ValueError,OSError,json.JSONDecodeError,_load('evidence_validator').EvidenceValidationError) as e: print(f'INVALID FINDING PROOF: {e}',file=sys.stderr); return 2
 finding['status']=target; tmp=path.with_suffix('.tmp'); tmp.write_text(yaml.safe_dump(finding,sort_keys=False)); tmp.replace(path); print(f'OK: {fid} {current} -> {target}'); return 0

def cmd_task_migrate_id(task_id: str) -> int:
    import re
    if not re.fullmatch(r"TASK-[0-9]+", task_id):
        print("INVALID TASK ID: must match TASK-[0-9]+", file=sys.stderr); return 2
    task=load_task(Path('.harness')); task.setdefault('task',{})['id']=task_id
    save_task(Path('.harness'),task); print(f"OK: task id -> {task_id}"); return 0

def cmd_task_classify(level: str, dimensions: dict[str, str]) -> int:
    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    if task.get("state") != "CREATED":
        print("task classify requires state CREATED", file=sys.stderr)
        return 1
    try:
        risk = _load("risk")
        profile = risk.classify(level, dimensions)
        _load("state_machine").require_legal("CREATED", "CLASSIFIED")
        workspace = _load("workspace")
        user_changes = workspace.snapshot().changed_paths
        task["risk"] = {
            "level": level, "profile": profile, "dimensions": dimensions,
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
    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    risk_record = task.get("risk")
    if not isinstance(risk_record, dict) or not reason.strip():
        print("RISK_ESCALATION_INVALID", file=sys.stderr)
        return 2
    try:
        risk = _load("risk")
        risk.validate_escalation(risk_record["level"], level)
    except Exception as exc:
        print(f"RISK_ESCALATION_INVALID: {exc}", file=sys.stderr)
        return 2
    risk_record["escalation_history"].append({"from": risk_record["level"], "to": level, "reason": reason})
    risk_record["level"] = level
    risk_record["profile"] = risk.PROFILES[level]
    save_task(harness_dir, task)
    print(f"OK: escalated to {level}/{risk_record['profile']}")
    return 0


def _verify_record(kind: str, rid: str, ref: str) -> int:
 import yaml,json
 hp=Path('.harness'); path=hp/("requirements.yaml" if kind=="requirement" else "invariants.yaml"); doc=yaml.safe_load(path.read_text()); key="requirements" if kind=="requirement" else "invariants"
 rec=next((x for x in doc.get(key,[]) if x.get('id')==rid),None)
 if not rec: print(f"{kind} not found: {rid}",file=sys.stderr); return 1
 ep=hp/'evidence'/(ref if ref.endswith('.json') else ref+'.json')
 try: ev=json.loads(ep.read_text())
 except Exception: print(f"INVALID EVIDENCE: {ref}",file=sys.stderr); return 2
 try:
  gate=_load('quality_gate'); current=_load('collect_evidence').workspace_fingerprint()
  _load('evidence_validator').validate_evidence(ev,current_head=gate.git_head(),current_workspace=current,expected_success=True)
 except Exception as exc: print(f"INVALID EVIDENCE: {exc}",file=sys.stderr); return 2
 field='evidence' if kind=='requirement' else 'verification'; rec.setdefault(field,[])
 if ref not in rec[field]: rec[field].append(ref)
 rec['status']='verified'; tmp=path.with_suffix('.tmp');tmp.write_text(yaml.safe_dump(doc,sort_keys=False));tmp.replace(path);print(f"OK: {rid} verified");return 0

def cmd_requirement_verify(rid,ref): return _verify_record('requirement',rid,ref)
def cmd_invariant_verify(rid,ref): return _verify_record('invariant',rid,ref)


def initialize_task_git(task: dict, head: str) -> None:
    """Set replacement-task immutable baseline and current HEAD together."""
    task["git"] = {"base_commit": head, "head": head}


def task_git_head_or_error() -> str:
    """Resolve required task baseline before any replacement-task mutation."""
    workspace = _load("workspace")
    return workspace.git_head()


def cmd_task_new(task_id: str, title: str = "") -> int:
 import shutil, datetime, re
 if not re.fullmatch(r"TASK-[0-9]+",task_id): print("INVALID TASK ID",file=sys.stderr);return 2
 h=Path('.harness'); old=load_task(h)
 if old.get('state') not in {'DONE','ESCALATED'}: print('task new requires DONE or ESCALATED task',file=sys.stderr);return 1
 try: head=task_git_head_or_error()
 except _load('workspace').WorkspaceError as exc: print(f'TASK_GIT_BASELINE_REQUIRED: {exc}',file=sys.stderr);return 2
 archive=h/'history'/f"{old['task']['id']}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}";archive.mkdir(parents=True)
 for name in ('current-task.yaml','requirements.yaml','invariants.yaml','gate.yaml','observability.yaml','findings','evidence'):
  src=h/name
  if src.exists(): shutil.copytree(src,archive/name) if src.is_dir() else shutil.copy2(src,archive/name)
 from harness.templates import templates_dir
 for name in ('current-task.yaml','requirements.yaml','invariants.yaml','gate.yaml','observability.yaml'):
  shutil.copy2(templates_dir()/name,h/name)
 for name in ('findings','evidence'):
  shutil.rmtree(h/name,ignore_errors=True);(h/name).mkdir()
 task=load_task(h);task['task']['id']=task_id;task['task']['title']=title;task['timestamps']['created_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();initialize_task_git(task,head)
 save_task(h,task);print(f'OK: archived task, created {task_id}');return 0

def cmd_task_recover(task_id: str, title: str, reason: str) -> int:
    """Archive an active task with an explicit recovery audit."""
    import datetime
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

    try:
        head = task_git_head_or_error()
    except _load("workspace").WorkspaceError as exc:
        print(f"TASK_GIT_BASELINE_REQUIRED: {exc}", file=sys.stderr)
        return 2

    old_id = old.get("task", {}).get("id") or "UNKNOWN"
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive = harness_dir / "history" / f"{old_id}-{timestamp}"
    try:
        archive.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print(f"RECOVERY_ARCHIVE_EXISTS: {archive}", file=sys.stderr)
        return 1

    for name in ("current-task.yaml", "requirements.yaml", "invariants.yaml", "gate.yaml", "observability.yaml"):
        source = harness_dir / name
        if source.exists():
            shutil.copy2(source, archive / name)

    audit = {
        "recovered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "reason": reason,
        "previous_task_id": old_id,
        "previous_state": old.get("state"),
        "replacement_task_id": task_id,
    }
    (archive / "recovery.yaml").write_text(yaml.safe_dump(audit, sort_keys=False))

    for name in ("findings", "evidence"):
        source = harness_dir / name
        if source.exists():
            shutil.move(str(source), str(archive / name))
        (harness_dir / name).mkdir()

    for name in ("current-task.yaml", "requirements.yaml", "invariants.yaml", "gate.yaml", "observability.yaml"):
        shutil.copy2(templates_dir() / name, harness_dir / name)
    task = load_task(harness_dir)
    task["task"]["id"] = task_id
    task["task"]["title"] = title
    task["timestamps"]["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    initialize_task_git(task, head)
    save_task(harness_dir, task)
    print(f"OK: recovered {old_id}, created {task_id}")
    return 0


AUTHORIZATION_ACTIONS = (
    "commit", "full_suite", "push", "create_mr", "ready_mr", "merge", "deploy",
)


def _authorization_record(granted: bool = False) -> dict:
    return {"granted": granted, "granted_at": None, "source": None}


def authorization_granted(task: dict, action: str) -> bool:
    """Check one action only; legacy authorization applies only to full suite."""
    normalized = (task.get("authorizations") or {}).get(action)
    if isinstance(normalized, dict):
        return normalized.get("granted") is True
    if action == "full_suite":
        return (task.get("authorization") or {}).get("full_suite", {}).get("granted") is True
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
 p=Path('.harness/impact.yaml')
 d=yaml.safe_load(p.read_text()) if p.exists() else {'impact':{'changed':[],'direct_dependents':[],'contracts':[],'risks':[],'required_tests':[],'full_suite':{'recommended':False,'reason':None}}}
 return p,d
def cmd_impact(action,value=None,reason=None):
 import yaml
 p,d=_impact(); i=d['impact']
 if action=='show': print(yaml.safe_dump(d,sort_keys=False));return 0
 key={'add-change':'changed','add-test':'required_tests','add-dependent':'direct_dependents','add-contract':'contracts','add-risk':'risks'}.get(action)
 if key:
  if value not in i[key]: i[key].append(value)
 elif action=='require-full-suite': i['full_suite']={'recommended':True,'reason':reason}
 p.write_text(yaml.safe_dump(d,sort_keys=False));return 0
