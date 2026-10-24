import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from collect_evidence import workspace_fingerprint


def synthetic_execution(nodes=(), exit_code=0):
    """Synthetic unit input only, never a claim of native execution qualification."""
    selected = sorted({node if "::" in node else node + "::test_fixture"
                       for node in (nodes or ["tests/fixture.py::test_fixture"])})
    return {"schema": "pytest-execution/v1", "runs": [{
        "collected": selected, "passed": selected if exit_code == 0 else [],
        "failed": selected if exit_code == 1 else [], "skipped": [],
        "assertion_failures": selected if exit_code == 1 else [],
        "errors": 0 if exit_code in {0, 1} else 1, "exit_code": exit_code,
    }]}


def write_evidence(repo, harness_dir, evidence_type, exit_code=0, name=None):
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    fp = workspace_fingerprint(repo)
    path = (
        harness_dir / "evidence" / (name or f"{evidence_type.replace('_', '-')}.json")
    )
    path.write_text(
        json.dumps(
            {
                "type": evidence_type,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "command": "true",
                "exit_code": exit_code,
                "commit": head,
                "workspace_fingerprint": fp,
                "workspace_fingerprint_after": fp,
                **({"test_execution": synthetic_execution(exit_code=exit_code)}
                   if evidence_type in {"unit_test", "integration_test", "contract_test"} else {}),
            }
        )
    )
    return path


def write_complexity_review(repo, harness_dir):
    path = write_evidence(repo, harness_dir, "review", name="complexity-review.json")
    record = json.loads(path.read_text())
    record["checks"] = {
        name: {"result": "not_applicable", "evidence": "fixture"}
        for name in ("delete", "reuse", "stdlib", "native", "yagni", "shrink")
    }
    record["review_scope"] = {"files": []}
    task_path = harness_dir / "current-task.yaml"
    impact_path = harness_dir / "impact.yaml"
    if task_path.is_file():
        from harness.workspace import observability_inspected_paths, project_task_scope

        task = yaml.safe_load(task_path.read_text()) or {}
        impact = {}
        if impact_path.is_file():
            impact = (yaml.safe_load(impact_path.read_text()) or {}).get("impact") or {}
        record["review_scope"]["files"] = list(
            project_task_scope(
                task,
                impact,
                inspected_paths=observability_inspected_paths(harness_dir),
            )
        )
    path.write_text(json.dumps(record))
    return path
