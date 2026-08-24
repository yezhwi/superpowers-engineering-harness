"""Control-plane subcommands (guide v0.1 section 34).

Thin wrappers over the deterministic scripts in <repo>/scripts. Logic is
imported from the scripts directory -- never re-implemented here, so the
CLI and the scripts can never diverge.
"""

import importlib.util
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


def gate_pass(harness_dir: Path) -> bool:
    """True iff the gate passes for harness_dir (no side effects)."""
    quality_gate = _load("quality_gate")
    head = quality_gate.git_head()
    try:
        status, _ = quality_gate.run_gate(harness_dir, head=head)
    except quality_gate.InvalidHarnessState:
        return False
    return status == "PASS"
