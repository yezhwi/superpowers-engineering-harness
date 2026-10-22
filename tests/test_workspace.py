"""Repository-state snapshots used by evidence, Gate, status, and review."""

import subprocess
import json
import os
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_candidate_git_home(tmp_path, monkeypatch):
    home = tmp_path / "git-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "config"))


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def committed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "tracked.py").write_text("value = 1\n")
    git(repo, "add", "tracked.py")
    git(repo, "commit", "-qm", "base")
    return repo


def candidate_repo(tmp_path: Path) -> Path:
    repo = committed_repo(tmp_path)
    harness = repo / ".harness"
    harness.mkdir()
    task = {
        "task": {"id": "TASK-1", "title": "candidate", "type": "feature", "description": ""},
        "state": "IMPLEMENTING",
        "risk": {"level": "Q3", "profile": "STRICT", "dimensions": {}},
        "scope": {"owned_paths": ["tracked.py", "feature.py"], "protected_user_paths": ["notes.md"]},
        "git": {"base_ref": "main", "base_commit": git(repo, "rev-parse", "HEAD"), "head_at_start": git(repo, "rev-parse", "HEAD"), "head": git(repo, "rev-parse", "HEAD")},
        "plan_reconciliation": {"enabled": True, "mode": "task_and_final"},
        "gate": {},
    }
    (harness / "gate.yaml").write_text(yaml.safe_dump({"gate": {"candidate_commit": {
        "format": "candidate-commit/v1", "capability_version": 1, "minimum_reader": "0.3.2",
    }}}))
    (harness / "current-task.yaml").write_text(yaml.safe_dump(task, sort_keys=False))
    return repo


def run_harness(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        ["/Users/Yezhiwei/anaconda3/envs/base3110/bin/python3", "-m", "harness.cli", *args],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
    )


@pytest.mark.parametrize("input_kind", ["hook", "filter", "sparse", "environment", "index_symlink"])
def test_candidate_prepare_refuses_git_inputs_before_discovery(tmp_path, monkeypatch, input_kind):
    from harness.candidate_commit import CandidateRefusal, prepare

    repo = candidate_repo(tmp_path)
    (repo / "tracked.py").write_text("value = 2\n")
    git(repo, "add", "tracked.py")
    index = repo / ".git/index"
    original = index.read_bytes()
    if input_kind == "hook":
        git(repo, "config", "core.hooksPath", str(tmp_path / "hooks"))
    elif input_kind == "filter":
        git(repo, "config", "filter.example.clean", "cat")
    elif input_kind == "sparse":
        git(repo, "config", "core.sparseCheckout", "true")
    elif input_kind == "environment":
        monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "foreign-index"))
    else:
        stored = tmp_path / "original-index"
        index.rename(stored)
        index.symlink_to(stored)
    with pytest.raises(CandidateRefusal, match="CANDIDATE_GIT_UNSUPPORTED"):
        prepare(repo, ["tracked.py"])
    assert index.read_bytes() == original
    assert not (repo / ".harness/evidence/candidate-prepared").exists()


@pytest.mark.parametrize('defect', ['schema', 'hash', 'domain'])
def test_candidate_status_refuses_tampered_preparation_identity(tmp_path, defect):
    from harness.candidate_commit import prepare

    repo = candidate_repo(tmp_path)
    (repo / 'tracked.py').write_text('value = 2\n')
    git(repo, 'add', 'tracked.py')
    prepared = prepare(repo, ['tracked.py'])
    path = repo / prepared['record']
    document = json.loads(path.read_text())
    if defect == 'schema':
        import hashlib
        document['unknown'] = True
        body = {key: value for key, value in document.items() if key != 'candidate_id'}
        identifier = 'sha256:' + hashlib.sha256(b'harness:candidate-prepared:v1\0' + json.dumps(
            body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        document['candidate_id'] = identifier
        prepared['candidate'] = identifier
        path = path.parent / (identifier[7:] + '.json')
    elif defect == 'hash':
        document['candidate_tree'] = '0' * 40
    else:
        document['domain'] = 'unrecognized/v1'
    path.write_text(json.dumps(document))
    before = (repo / '.git/index').read_bytes()
    result = run_harness(repo, 'candidate', 'status', '--candidate', prepared['candidate'], '--json')
    assert result.returncode == 1
    envelope = json.loads(result.stdout)
    assert envelope['ok'] is False and envelope['reason_code'] == 'CANDIDATE_SCHEMA_UNSUPPORTED'
    assert (repo / '.git/index').read_bytes() == before


@pytest.mark.parametrize('path_kind', ['absolute', 'traversal', 'parent_symlink'])
def test_candidate_input_facts_never_open_outside_repository(tmp_path, path_kind):
    from harness.candidate_commit import CandidateRefusal, _file_fact

    root = tmp_path / 'repository'
    root.mkdir()
    external = tmp_path / 'external'
    external.mkdir()
    (external / 'private.txt').write_text('outside bytes must not be read')
    if path_kind == 'absolute':
        path = str(external / 'private.txt')
    elif path_kind == 'traversal':
        path = '../external/private.txt'
    else:
        (root / 'alias').symlink_to(external, target_is_directory=True)
        path = 'alias/private.txt'
    with pytest.raises(CandidateRefusal):
        _file_fact(root, path)


def test_candidate_binding_includes_index_identity_not_only_equal_bytes(tmp_path):
    import json
    from harness.candidate_commit import _input_consistent, prepare

    repo = candidate_repo(tmp_path)
    (repo / "tracked.py").write_text("value = 2\n")
    git(repo, "add", "tracked.py")
    result = prepare(repo, ["tracked.py"])
    candidate = json.loads((repo / result["record"]).read_text())
    index = repo / ".git/index"
    replacement = repo / ".git/replacement-index"
    replacement.write_bytes(index.read_bytes())
    replacement.replace(index)
    assert not _input_consistent(repo, candidate, head=candidate["parent"])


def test_candidate_records_use_private_durable_publication(tmp_path):
    import stat
    from harness.candidate_commit import prepare

    repo = candidate_repo(tmp_path)
    (repo / "tracked.py").write_text("value = 2\n")
    git(repo, "add", "tracked.py")
    result = prepare(repo, ["tracked.py"])
    path = repo / result["record"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert not list((repo / ".harness/.transactions").iterdir())


@pytest.mark.parametrize('name', ['current-task.yaml', 'gate.yaml', 'requirements.yaml',
    'invariants.yaml', 'impact.yaml', 'alignment.yaml', 'plan.yaml'])
def test_candidate_prepare_never_blocks_on_special_control_metadata(tmp_path, name):
    import sys
    repo = candidate_repo(tmp_path)
    (repo / 'tracked.py').write_text('value = 2\n')
    git(repo, 'add', 'tracked.py')
    path = repo / '.harness' / name
    path.unlink(missing_ok=True)
    os.mkfifo(path)
    index = (repo / '.git/index').read_bytes()
    env = {**os.environ, 'PYTHONPATH': str(REPO_ROOT / 'src')}
    try:
        result = subprocess.run([sys.executable, '-m', 'harness.cli', 'candidate', 'prepare',
                                 '--path', 'tracked.py', '--json'], cwd=repo, env=env,
                                capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        pytest.fail('candidate command blocked opening control metadata FIFO')
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)['ok'] is False
    assert (repo / '.git/index').read_bytes() == index
    assert not list((repo / '.harness/evidence/candidate-prepared').glob('*.json'))


def test_candidate_prepare_refuses_unadapted_live_architecture_domain(tmp_path):
    repo = candidate_repo(tmp_path)
    (repo / 'tracked.py').write_text('value = 2\n')
    git(repo, 'add', 'tracked.py')
    path = repo / '.harness/gate.yaml'
    policy = yaml.safe_load(path.read_text())
    policy['gate']['architecture'] = {'mode': 'required'}
    path.write_text(yaml.safe_dump(policy))
    index = (repo / '.git/index').read_bytes()
    result = run_harness(repo, 'candidate', 'prepare', '--path', 'tracked.py', '--json')
    assert result.returncode == 1
    outcome = json.loads(result.stdout)
    assert outcome['reason_code'] == 'CANDIDATE_UNSUPPORTED'
    assert (repo / '.git/index').read_bytes() == index
    assert not list((repo / '.harness/evidence/candidate-prepared').glob('*.json'))
    assert yaml.safe_load(path.read_text())['gate']['architecture']['mode'] == 'required'


def test_candidate_policy_is_enrolled_in_gate_contract_not_task_summary(tmp_path):
    from harness.candidate_commit import CandidateRefusal, prepare

    repo = candidate_repo(tmp_path)
    task_path = repo / ".harness" / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task.pop("gate")
    task_path.write_text(yaml.safe_dump(task))
    gate_path = repo / ".harness" / "gate.yaml"
    policy = yaml.safe_load(gate_path.read_text())["gate"]["candidate_commit"]
    (repo / "tracked.py").write_text("value = 2\n")
    git(repo, "add", "tracked.py")

    assert prepare(repo, ["tracked.py"])["status"] == "PREPARED"
    task["gate"] = {"candidate_commit": policy}
    task_path.write_text(yaml.safe_dump(task))
    gate_path.write_text(yaml.safe_dump({"gate": {}}))
    with pytest.raises(CandidateRefusal, match="CANDIDATE_POLICY_REQUIRED"):
        prepare(repo, ["tracked.py"])


def test_candidate_manifest_binds_complete_inputs_without_committing_protected_paths(tmp_path):
    repo = candidate_repo(tmp_path)
    (repo / "tracked.py").write_text("value = 2\n")
    git(repo, "add", "tracked.py")
    (repo / "feature.py").write_text("enabled = True\n")
    git(repo, "add", "feature.py")
    (repo / "tracked.py").write_text("value = 3\n")
    (repo / "untracked.txt").write_text("untracked\n")
    (repo / "notes.md").write_text("protected\n")
    index_before = (repo / ".git" / "index").read_bytes()

    result = run_harness(repo, "candidate", "prepare", "--path", "tracked.py", "--path", "feature.py", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    record = json.loads((repo / payload["artifact_ref"]).read_text())
    assert payload['ok'] is True and payload['phase'] == 'PREPARED'
    assert record["selected"] == [
        {"action": "upsert", "index_mode": "100644", "index_oid": git(repo, "rev-parse", ":feature.py"), "path": "feature.py"},
        {"action": "upsert", "index_mode": "100644", "index_oid": git(repo, "rev-parse", ":tracked.py"), "path": "tracked.py"},
    ]
    assert record["inputs"]["untracked"][0]["path"] == "notes.md" or record["inputs"]["untracked"][0]["path"] == "untracked.txt"
    assert any(item["path"] == "notes.md" for item in record["inputs"]["protected"])
    assert (repo / ".git" / "index").read_bytes() == index_before
    assert git(repo, "show", f'{record["candidate_tree"]}:tracked.py') == "value = 2"
    assert (repo / "notes.md").read_text() == "protected\n"


def test_candidate_formation_refuses_unsupported_or_unowned_inputs(tmp_path):
    repo = candidate_repo(tmp_path)
    (repo / "outside.py").write_text("outside = True\n")
    git(repo, "add", "outside.py")
    index_before = (repo / ".git" / "index").read_bytes()

    result = run_harness(repo, "candidate", "prepare", "--path", "outside.py", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload['ok'] is False and payload['reason_code'] == 'CANDIDATE_UNSUPPORTED'
    assert (repo / ".git" / "index").read_bytes() == index_before
    assert not (repo / ".harness" / "evidence" / "candidate-prepared").exists()


def test_candidate_operations_preserve_unowned_bytes_and_never_open_special_nodes(tmp_path):
    repo = candidate_repo(tmp_path)
    (repo / "tracked.py").write_text("value = 2\n")
    git(repo, "add", "tracked.py")
    unowned = repo / "user.bin"
    unowned.write_bytes(b"user-owned\x00bytes")
    special = repo / "never-open"
    os.mkfifo(special)
    try:
        result = run_harness(repo, "candidate", "prepare", "--path", "tracked.py", "--json")
        assert result.returncode == 1
        assert json.loads(result.stdout)['reason_code'] == 'CANDIDATE_UNSUPPORTED'
        assert unowned.read_bytes() == b"user-owned\x00bytes"
    finally:
        special.unlink()


def test_snapshot_lists_all_business_changes_and_ignores_harness(tmp_path):
    """Break caught: a dirty/staged/untracked implementation file escapes evidence scope."""
    from harness.workspace import snapshot

    repo = committed_repo(tmp_path)
    (repo / "tracked.py").write_text("value = 2\n")
    (repo / "staged.py").write_text("staged = True\n")
    git(repo, "add", "staged.py")
    (repo / "untracked.py").write_text("untracked = True\n")
    (repo / ".harness").mkdir()
    (repo / ".harness" / "runtime.json").write_text("{}")

    state = snapshot(repo)

    assert state.changed_paths == ("staged.py", "tracked.py", "untracked.py")
    assert state.fingerprint.startswith("sha256:")
    assert len(state.fingerprint) == 71


def test_product_fingerprint_ignores_tracked_and_untracked_harness_metadata(tmp_path):
    """Break caught: writing requirement verification stale-s product evidence."""
    from harness.workspace import control_plane_fingerprint, snapshot

    repo = committed_repo(tmp_path)
    harness = repo / ".harness"
    harness.mkdir()
    (harness / "requirements.yaml").write_text("requirements: []\n")
    git(repo, "add", "-f", ".harness/requirements.yaml")
    git(repo, "commit", "-qm", "track harness")
    before = snapshot(repo)
    control_before = control_plane_fingerprint(harness)

    (harness / "requirements.yaml").write_text("requirements: [{id: REQ-001}]\n")
    (harness / "evidence").mkdir()
    (harness / "evidence" / "unit-test.json").write_text("{}\n")
    after = snapshot(repo)

    assert after.fingerprint == before.fingerprint
    assert after.changed_paths == before.changed_paths
    assert control_plane_fingerprint(harness) != control_before


def test_product_fingerprint_changes_when_covered_product_test_changes(tmp_path):
    """Break caught: editing a product test leaves evidence marked fresh."""
    from harness.workspace import snapshot

    repo = committed_repo(tmp_path)
    backend = repo / "backend" / "tests"
    backend.mkdir(parents=True)
    target = backend / "test_foo.py"
    target.write_text("def test_ok():\n    assert True\n")
    git(repo, "add", "backend/tests/test_foo.py")
    git(repo, "commit", "-qm", "product tests")
    before = snapshot(repo).fingerprint
    target.write_text("def test_ok():\n    assert False\n")

    assert snapshot(repo).fingerprint != before


def test_changed_paths_since_includes_committed_and_working_paths(tmp_path):
    from harness.workspace import changed_paths_since

    repo = committed_repo(tmp_path)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    (repo / "committed.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "committed.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "change"], cwd=repo, check=True)
    (repo / "working.py").write_text("value = 2\n")

    assert changed_paths_since(base, repo) == ("committed.py", "working.py")


def test_protected_paths_fingerprint_changes_when_preexisting_dirty_file_changes(
    tmp_path,
):
    from harness.workspace import protected_paths_fingerprint

    repo = committed_repo(tmp_path)
    path = repo / "tracked.py"
    path.write_text("value = 2\n")
    before = protected_paths_fingerprint(("tracked.py",), repo)
    path.write_text("value = 3\n")

    assert protected_paths_fingerprint(("tracked.py",), repo) != before


def test_review_scope_with_base_at_head_includes_dirty_and_untracked_files(tmp_path):
    """Break caught: base==HEAD produces empty complexity review despite workspace changes."""
    from harness.workspace import review_scope

    repo = committed_repo(tmp_path)
    (repo / "tracked.py").write_text("value = 2\n")
    (repo / "new_service.py").write_text("enabled = True\n")

    scope = review_scope("HEAD", repo)

    assert scope.base_commit == scope.head_commit
    assert scope.files == ("new_service.py", "tracked.py")


def test_review_scope_includes_committed_delta_from_merge_base(tmp_path):
    """Break caught: committed changes between base and HEAD are absent from review scope."""
    from harness.workspace import review_scope

    repo = committed_repo(tmp_path)
    (repo / "committed.py").write_text("committed = True\n")
    git(repo, "add", "committed.py")
    git(repo, "commit", "-qm", "feature")

    scope = review_scope("HEAD~1", repo)

    assert scope.files == ("committed.py",)
    assert scope.base_commit == git(repo, "rev-parse", "HEAD~1")
    assert scope.head_commit == git(repo, "rev-parse", "HEAD")


def test_v2_user_change_fingerprint_preserves_unadopted_path_baseline(tmp_path):
    from harness.workspace import (
        aggregate_protected_path_fingerprints,
        protected_path_fingerprints,
        protected_user_changes_fingerprint,
    )

    repo = committed_repo(tmp_path)
    (repo / "other.py").write_text("value = 1\n")
    git(repo, "add", "other.py")
    git(repo, "commit", "-qm", "add other")
    baseline = protected_path_fingerprints(("other.py", "tracked.py"), repo)
    (repo / "tracked.py").write_text("value = 2\n")
    user_changes = {
        "version": 2,
        "paths": ["other.py"],
        "path_fingerprints": {"other.py": baseline["other.py"]},
        "fingerprint": aggregate_protected_path_fingerprints(
            {"other.py": baseline["other.py"]}
        ),
    }

    assert protected_user_changes_fingerprint(user_changes, repo_root=repo) == user_changes["fingerprint"]


def test_v2_git_fingerprint_handles_tracked_deletion(tmp_path):
    from harness.workspace import protected_path_fingerprints

    repo = committed_repo(tmp_path)
    baseline = protected_path_fingerprints(("tracked.py",), repo)
    (repo / "tracked.py").unlink()
    assert protected_path_fingerprints(("tracked.py",), repo) != baseline


def test_v2_missing_untracked_path_fails_closed(tmp_path):
    from harness.workspace import WorkspaceError, protected_path_fingerprints

    repo = committed_repo(tmp_path)
    path = repo / "user.md"
    path.write_text("baseline\n")
    protected_path_fingerprints(("user.md",), repo)
    path.unlink()
    with pytest.raises(WorkspaceError):
        protected_path_fingerprints(("user.md",), repo)


def test_v2_protected_fingerprint_detects_changed_path(tmp_path):
    from harness.workspace import (
        aggregate_protected_path_fingerprints,
        protected_path_fingerprints,
        protected_user_changes_fingerprint,
    )

    repo = committed_repo(tmp_path)
    baseline = protected_path_fingerprints(("tracked.py",), repo)
    user_changes = {
        "version": 2,
        "paths": ["tracked.py"],
        "path_fingerprints": baseline,
        "fingerprint": aggregate_protected_path_fingerprints(baseline),
    }
    (repo / "tracked.py").write_text("value = 2\n")

    assert protected_user_changes_fingerprint(user_changes, repo_root=repo) != user_changes["fingerprint"]
