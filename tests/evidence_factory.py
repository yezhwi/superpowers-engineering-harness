import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from collect_evidence import workspace_fingerprint


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
