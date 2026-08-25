import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from collect_evidence import workspace_fingerprint

def write_evidence(repo, harness_dir, evidence_type, exit_code=0, name=None):
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    fp = workspace_fingerprint(repo)
    path = harness_dir / "evidence" / (name or f"{evidence_type.replace('_','-')}.json")
    path.write_text(json.dumps({"type": evidence_type, "timestamp": "2026-01-01T00:00:00+00:00", "command": "true", "exit_code": exit_code, "commit": head, "workspace_fingerprint": fp, "workspace_fingerprint_after": fp}))
    return path


def write_complexity_review(repo, harness_dir):
    return write_evidence(repo, harness_dir, "review", name="complexity-review.json")
