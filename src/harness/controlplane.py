"""Control-plane subcommands (guide v0.1 section 34).

Thin wrappers over the deterministic scripts in <repo>/scripts. Logic is
imported from the scripts directory -- never re-implemented here, so the
CLI and the scripts can never diverge.
"""

import importlib.util
import json
import sys
from pathlib import Path

from harness.templates import templates_dir


class HarnessStateError(Exception):
    """Invalid harness state (maps to exit code 2)."""


def _scripts_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "scripts"
        if (candidate / "state_machine.py").is_file():
            return candidate
    raise HarnessStateError("could not locate scripts/ directory")


def _load(name: str):
    scripts = _scripts_dir()
    if str(scripts) not in sys.path:
        # script modules import each other by top-level name
        sys.path.insert(0, str(scripts))
    path = scripts / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"harness_scripts_{name}",
                                                  path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def cmd_status() -> int:
    return _load("harness_status").main([])


def cmd_transition(target: str) -> int:
    state_machine = _load("state_machine")
    harness_dir = Path(".harness")
    task = load_task(harness_dir)
    current = task.get("state")
    # Reject malformed task identity/state before it can advance toward Gate.
    try:
        _load("quality_gate").validate_schema(
            task, "task.schema.json", harness_dir / "current-task.yaml")
    except Exception as exc:
        print(f"INVALID_HARNESS_STATE: {exc}", file=sys.stderr)
        return 2
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


def cmd_evidence(evidence_type: str, command: str) -> int:
    collect_evidence = _load("collect_evidence")
    return collect_evidence.main(
        ["--type", evidence_type, "--command", command])


def cmd_gate() -> int:
    quality_gate = _load("quality_gate")
    return quality_gate.main([])


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


def cmd_converge() -> int:
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
        task["gate"] = {"status": "BLOCKED", "blocked_by": blockers}
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
        task["gate"] = {"status": "BLOCKED", "blocked_by": blockers}
        save_task(harness_dir, task)
        print("DECISION: ESCALATED")
        print("REASON: MAX_ITERATIONS")
        for b in blockers:
            print(f"  blocker: {b}")
        return 0

    state_machine.require_legal("GATING", "BLOCKED")
    task["state"] = "BLOCKED"
    task["iteration"] = iteration + 1
    task["gate"] = {"status": "BLOCKED", "blocked_by": blockers}
    save_task(harness_dir, task)
    print(f"DECISION: CONTINUE (iteration {task['iteration']} /"
      f" {max_iterations})")
    for b in blockers:
        print(f"  blocker: {b}")
    return 0


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
def cmd_finding_transition(fid,target,evidence=None,test=None,attempt=None,reason=None):
 import yaml,datetime,json
 path=None; finding=None
 for p in Path('.harness/findings').glob('*.yaml'):
  x=yaml.safe_load(p.read_text())
  if isinstance(x,dict) and x.get('id')==fid: path,finding=p,x; break
 if not path: print(f'finding not found: {fid}',file=sys.stderr); return 1
 current=finding.get('status')
 if target not in _FINDING_TRANSITIONS.get(current,set()): print(f'INVALID FINDING TRANSITION: {current} -> {target}',file=sys.stderr); return 1
 def proof(ref,ok):
  if not ref: raise ValueError('missing --evidence')
  p=Path('.harness/evidence')/(ref if ref.endswith('.json') else ref+'.json')
  d=json.loads(p.read_text()); head=_load('quality_gate').git_head()
  if d.get('commit')!=head or (d.get('exit_code')==0)!=ok: raise ValueError('evidence is not fresh expected proof')
 try:
  if target=='REPRODUCING':
   if not attempt: raise ValueError('REPRODUCING requires --attempt')
   finding.setdefault('attempts',[]).append(attempt)
  elif target=='CONFIRMED':
   if not test: raise ValueError('CONFIRMED requires --test')
   proof(evidence,False); finding['test']=test; finding['regression_test']={'path':test,'red_evidence':evidence}; finding['confirmed_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
  elif target=='FIXED': proof(evidence,True); finding['regression_test']['green_evidence']=evidence
  elif target=='VERIFIED': proof(evidence,True); finding['evidence']=evidence; finding['verified_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
  elif target=='REJECTED':
   if not reason or not finding.get('attempts'): raise ValueError('REJECTED requires attempts and --reason')
   finding['rejection_reason']=reason
 except (ValueError,OSError,json.JSONDecodeError) as e: print(f'INVALID FINDING PROOF: {e}',file=sys.stderr); return 2
 finding['status']=target; tmp=path.with_suffix('.tmp'); tmp.write_text(yaml.safe_dump(finding,sort_keys=False)); tmp.replace(path); print(f'OK: {fid} {current} -> {target}'); return 0

def cmd_task_migrate_id(task_id: str) -> int:
    import re
    if not re.fullmatch(r"TASK-[0-9]+", task_id):
        print("INVALID TASK ID: must match TASK-[0-9]+", file=sys.stderr); return 2
    task=load_task(Path('.harness')); task.setdefault('task',{})['id']=task_id
    save_task(Path('.harness'),task); print(f"OK: task id -> {task_id}"); return 0

def _verify_record(kind: str, rid: str, ref: str) -> int:
 import yaml,json
 hp=Path('.harness'); path=hp/("requirements.yaml" if kind=="requirement" else "invariants.yaml"); doc=yaml.safe_load(path.read_text()); key="requirements" if kind=="requirement" else "invariants"
 rec=next((x for x in doc.get(key,[]) if x.get('id')==rid),None)
 if not rec: print(f"{kind} not found: {rid}",file=sys.stderr); return 1
 ep=hp/'evidence'/(ref if ref.endswith('.json') else ref+'.json')
 try: ev=json.loads(ep.read_text())
 except Exception: print(f"INVALID EVIDENCE: {ref}",file=sys.stderr); return 2
 if ev.get('exit_code')!=0: print("INVALID EVIDENCE: command failed",file=sys.stderr); return 2
 try:
  gate=_load('quality_gate'); current=_load('collect_evidence').workspace_fingerprint()
  if ev.get('commit')!=gate.git_head() or ev.get('workspace_fingerprint')!=current or ev.get('workspace_fingerprint_after')!=current:
   print("INVALID EVIDENCE: stale workspace snapshot",file=sys.stderr); return 2
 except Exception as exc: print(f"INVALID EVIDENCE: {exc}",file=sys.stderr); return 2
 field='evidence' if kind=='requirement' else 'verification'; rec.setdefault(field,[])
 if ref not in rec[field]: rec[field].append(ref)
 rec['status']='verified'; tmp=path.with_suffix('.tmp');tmp.write_text(yaml.safe_dump(doc,sort_keys=False));tmp.replace(path);print(f"OK: {rid} verified");return 0

def cmd_requirement_verify(rid,ref): return _verify_record('requirement',rid,ref)
def cmd_invariant_verify(rid,ref): return _verify_record('invariant',rid,ref)

def cmd_task_new(task_id: str, title: str = "") -> int:
 import shutil, datetime, re
 if not re.fullmatch(r"TASK-[0-9]+",task_id): print("INVALID TASK ID",file=sys.stderr);return 2
 h=Path('.harness'); old=load_task(h)
 if old.get('state') not in {'DONE','ESCALATED'}: print('task new requires DONE or ESCALATED task',file=sys.stderr);return 1
 archive=h/'history'/f"{old['task']['id']}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}";archive.mkdir(parents=True)
 for name in ('current-task.yaml','requirements.yaml','invariants.yaml','gate.yaml','findings','evidence'):
  src=h/name
  if src.exists(): shutil.copytree(src,archive/name) if src.is_dir() else shutil.copy2(src,archive/name)
 from harness.templates import templates_dir
 for name in ('current-task.yaml','requirements.yaml','invariants.yaml','gate.yaml'):
  shutil.copy2(templates_dir()/name,h/name)
 for name in ('findings','evidence'):
  shutil.rmtree(h/name,ignore_errors=True);(h/name).mkdir()
 task=load_task(h);task['task']['id']=task_id;task['task']['title']=title;save_task(h,task);print(f'OK: archived task, created {task_id}');return 0
