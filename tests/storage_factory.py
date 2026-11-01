"""Temporary layout fixtures only; never an activation grant or product evidence."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPABILITY = "harness-storage-layout/v1"


def cli(repo, *args, timeout=20):
    return subprocess.run(
        [sys.executable, "-B", "-m", "harness.cli", *args], cwd=repo,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True, timeout=timeout, check=False,
    )


def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                    "commit", "--allow-empty", "-qm", "base"], cwd=repo, check=True)
    result = cli(repo, "init")
    assert result.returncode == 0, result.stderr
    return repo


def identity(path):
    info = path.lstat()
    return [info.st_dev, info.st_ino]


def fixture_store(repo):
    """Explicit test-side setup, not a supported production writer."""
    store = repo / ".harness-store"
    store.mkdir(mode=0o700)
    for name in ["operations", "history/archives", "retained/roots", "experiments", "receipts", "quarantine"]:
        (store / name).mkdir(parents=True, mode=0o700)
    header = {
        "version": 1, "kind": "store", "store_id": "1" * 32,
        "workspace_id": "2" * 32, "workspace_root": str(repo.resolve()),
        "workspace_identity": identity(repo), "store_identity": identity(store),
        "capabilities": [CAPABILITY],
    }
    binding = {
        "version": 1, "kind": "binding", "store_id": header["store_id"],
        "workspace_id": header["workspace_id"], "generation_id": "3" * 32,
        "root_identity": identity(repo / ".harness"), "store_identity": identity(store),
        "capabilities": [CAPABILITY],
    }
    (store / "store.yaml").write_text(json.dumps(header))
    (repo / ".harness/storage-binding.yaml").write_text(json.dumps(binding))
    import yaml

    gate_path = repo / '.harness/gate.yaml'
    gate = yaml.safe_load(gate_path.read_bytes())
    gate['gate']['storage_layout'] = {'version': 1, 'required_capabilities': [CAPABILITY]}
    gate_path.write_text(yaml.safe_dump(gate))
    return store, header, binding
