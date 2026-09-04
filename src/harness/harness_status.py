#!/usr/bin/env python3
"""harness_status.py -- unified persisted-state view.

Reads <harness-dir>/current-task.yaml and prints status.

Exit codes:
  0 = state valid and consistent
  1 = usage error
  2 = INVALID_HARNESS_STATE (missing file, unknown state,
      or DONE without gate PASS)
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

from .evidence_validator import project_evidence
from .state_machine import STATES, is_legal
from .workspace import WorkspaceError, snapshot

TEMPLATE_DEFAULTS = {
    "task": {"id": "UNKNOWN", "title": ""},
    "state": None,
    "iteration": 0,
    "max_iterations": 5,
    "verification": {},
    "findings": {},
    "gate": {"status": "unknown", "blocked_by": []},
}


def _load(harness_dir: Path):
    path = harness_dir / "current-task.yaml"
    if not path.exists():
        print(f"INVALID_HARNESS_STATE: missing {path}", file=sys.stderr)
        return None
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        print(f"INVALID_HARNESS_STATE: bad YAML: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(
            f"INVALID_HARNESS_STATE: {path} is not a mapping",
            file=sys.stderr,
        )
        return None
    for key, default in TEMPLATE_DEFAULTS.items():
        data.setdefault(key, {} if isinstance(default, dict) else default)
        if isinstance(default, dict):
            for k, v in default.items():
                data[key].setdefault(k, v)
    return data


def _validate(data) -> bool:
    state = data.get("state")
    if state not in STATES:
        print(f"INVALID_HARNESS_STATE: unknown state {state!r}", file=sys.stderr)
        return False
    # LAW 1: no DONE without quality gate PASS. Only legal entry to DONE
    # is CONVERGED -> DONE; a persisted DONE must show gate PASS.
    if state == "DONE" and data["gate"].get("status") != "PASS":
        print(
            "INVALID_HARNESS_STATE: DONE without gate PASS "
            "(only CONVERGED -> DONE is legal)",
            file=sys.stderr,
        )
        return False
    prev = data.get("previous_state")
    if prev is not None:
        if prev not in STATES:
            print(
                f"INVALID_HARNESS_STATE: unknown previous_state {prev!r}",
                file=sys.stderr,
            )
            return False
        if not is_legal(prev, state):
            print(
                f"INVALID_HARNESS_STATE: {prev} -> {state} is illegal", file=sys.stderr
            )
            return False
    return True


def _evidence_rows(harness_dir: Path):
    """Read-only current Evidence projection; never write task or gate state."""
    evidence_dir = harness_dir / "evidence"
    if not evidence_dir.is_dir():
        return []
    try:
        workspace = snapshot()
    except WorkspaceError:
        return []
    rows = []
    for path in sorted(evidence_dir.glob("*.json")):
        projection = project_evidence(
            path,
            current_head=workspace.head,
            current_workspace=workspace.fingerprint,
            expected_success=True,
        )
        record = projection.record or {}
        rows.append((record.get("type", path.stem), projection, record))
    return rows


def _render(data, harness_dir: Path) -> str:
    ver = data["verification"]
    find = data["findings"]
    gate = data["gate"]
    lines = [
        f"{data['task']['id']}  {data['task'].get('title', '')}",
        "",
        f"State        {data['state']}",
        f"Iteration    {data['iteration']} / {data['max_iterations']}",
        "",
        f"Build        {ver.get('build', 'unknown')}",
        f"Unit Tests   {ver.get('unit_test', 'unknown')}",
        f"Integration  {ver.get('integration_test', 'unknown')}",
    ]
    rows = _evidence_rows(harness_dir)
    if rows:
        lines.extend(["", "Evidence"])
        for evidence_type, projection, record in rows:
            lines.append(
                f"  {evidence_type:<16} {projection.status.value:<7} "
                f"exit={record.get('exit_code', '?')}  {record.get('command', '')}"
            )
            if projection.code:
                lines.append(f"    {projection.code}")
    lines.extend(
        [
            "",
            "Findings",
            f"  Critical   {find.get('critical', 0)}",
            f"  Major      {find.get('major', 0)}",
            f"  Minor      {find.get('minor', 0)}",
            "",
            f"Gate         {gate.get('status', 'unknown')}",
        ]
    )
    try:
        from .decision import active_decisions, load_decisions

        decisions = load_decisions(harness_dir)
        active = active_decisions(harness_dir)
    except Exception:
        decisions = []
        active = []
    if decisions:
        lines.extend(
            [
                "",
                "Decisions",
                f"  accepted: {len(active)}",
                f"  proposed: {sum(record['status'] == 'PROPOSED' for record in decisions)}",
            ]
        )
        lines.extend(
            f"  {record['id']} {record['topic']} = {record['selected']['option']}"
            for record in active
        )
    try:
        impact = yaml.safe_load((harness_dir / "impact.yaml").read_text()) or {}
        interfaces = [
            item
            for item in impact.get("impact", {}).get("interfaces", [])
            if item.get("visibility") == "external"
        ]
    except (OSError, yaml.YAMLError):
        interfaces = []
    if interfaces:
        compatibility = ", ".join(
            sorted({item.get("compatibility", "undeclared") for item in interfaces})
        )
        lines.extend(
            [
                "",
                "Interfaces",
                f"  public changes: {len(interfaces)}",
                f"  compatibility: {compatibility}",
            ]
        )
    blocked_by = gate.get("blocked_by") or []
    if blocked_by:
        lines.append("")
        lines.append("Blocking")
        lines.extend(f"  {b}" for b in blocked_by)
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Engineering Harness status")
    parser.add_argument(
        "--harness-dir",
        default=".harness",
        help="directory containing current-task.yaml",
    )
    args = parser.parse_args(argv)

    data = _load(Path(args.harness_dir))
    if data is None:
        return 2
    if not _validate(data):
        return 2
    print(_render(data, Path(args.harness_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
