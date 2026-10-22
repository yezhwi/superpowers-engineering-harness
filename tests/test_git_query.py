"""Bounded Git-only content queries used by protected snapshots."""

import pytest
import subprocess

from harness.git_query import GitQueryError, _validate


@pytest.fixture(autouse=True)
def isolated_git_home(tmp_path, monkeypatch):
    # Real mutation policy must inspect, not silently disable, user configuration.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "config"))


def test_hash_object_accepts_single_repo_relative_path():
    _validate(("hash-object", "--", "notes/user.md"))


@pytest.mark.parametrize("args", [
    ("hash-object", "--", "../outside"),
    ("hash-object", "--", "/tmp/outside"),
    ("hash-object", "--", "notes/../../outside"),
    ("hash-object", "--", "-w"),
    ("hash-object", "-w", "--", "notes/user.md"),
    ("hash-object", "--", "a.md", "b.md"),
    ("hash-object", "--", "."),
])
def test_hash_object_rejects_unbounded_queries(args):
    with pytest.raises(GitQueryError, match="GIT_QUERY_INVALID"):
        _validate(args)


def test_mutating_git_adapter_has_fixed_argv_environment_and_safe_allowlist(tmp_path):
    from harness.git_mutation import GitMutationError, _environment, update_ref

    assert set(key for key in _environment() if key.startswith("GIT_")) == {"GIT_TERMINAL_PROMPT"}
    with pytest.raises(GitMutationError, match="GIT_MUTATION_REF_INVALID"):
        update_ref(tmp_path, "HEAD", "a" * 40, "b" * 40)
    with pytest.raises(GitMutationError, match="GIT_MUTATION_ENV_UNSUPPORTED"):
        _environment({"GIT_INDEX_FILE": "outside"})


@pytest.mark.parametrize('drift', [None, 'worktree', 'index', 'untracked', 'semantic', 'git_config', 'proof'])
def test_candidate_commit_revalidates_all_inputs_and_uses_expected_old_ref_cas(tmp_path, monkeypatch, drift):
    from harness.git_mutation import GitMutationError, commit_tree, update_ref

    if drift is not None:
        import yaml
        from test_transaction_recovery import _prepared_candidate_intent
        from harness.candidate_commit import CandidateRefusal, controlled_commit

        fixture = tmp_path / 'fixture'
        fixture.mkdir()
        repo, operation, operation_path, task = _prepared_candidate_intent(fixture, monkeypatch, gate_bound=True)
        operation_path.unlink()
        task['authorizations']['commit'] = {'granted': True, 'source': 'user', 'granted_at': '2026-01-01T00:00:00+00:00'}
        (repo / '.harness/current-task.yaml').write_text(yaml.safe_dump(task))
        if drift == 'worktree':
            (repo / 'a.py').write_text('value = 3\n')
        elif drift == 'index':
            (repo / 'a.py').write_text('value = 3\n')
            subprocess.run(['git', 'add', 'a.py'], cwd=repo, check=True)
        elif drift == 'untracked':
            (repo / 'new-user-file').write_text('keep this\n')
        elif drift == 'semantic':
            task['task']['type'] = 'bugfix'
            (repo / '.harness/current-task.yaml').write_text(yaml.safe_dump(task))
        elif drift == 'git_config':
            subprocess.run(['git', 'config', 'user.name', 'Changed Identity'], cwd=repo, check=True)
        else:
            proof = next((repo / '.harness/evidence/candidate-proof').glob('*.json'))
            proof.write_text('{}')
        message = fixture / 'message.txt'
        message.write_text('candidate\n')
        index = (repo / '.git/index').read_bytes()
        with pytest.raises(CandidateRefusal, match='CANDIDATE_(DRIFT|GATE_BLOCKED|GIT_UNSUPPORTED)'):
            controlled_commit(repo, operation['payload']['candidate_id'], message)
        assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip() == operation['payload']['parent']
        assert (repo / '.git/index').read_bytes() == index
        assert not list(operation_path.parent.iterdir())
        return

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    (tmp_path / "a").write_text("a\n")
    subprocess.run(["git", "add", "a"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    parent = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=tmp_path, text=True).strip()
    identity = {key: value for key, value in {
        "GIT_AUTHOR_NAME": "Harness", "GIT_AUTHOR_EMAIL": "h@example.com", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
        "GIT_COMMITTER_NAME": "Harness", "GIT_COMMITTER_EMAIL": "h@example.com", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
    }.items()}
    proposed = commit_tree(tmp_path, tree, parent, b"candidate\n", identity)
    update_ref(tmp_path, "refs/heads/master", proposed, parent)
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip() == proposed
    with pytest.raises(GitMutationError, match="CANDIDATE_REF_CONFLICT"):
        update_ref(tmp_path, "refs/heads/master", parent, parent)


@pytest.mark.parametrize("unsupported", ["hook", "signing", "environment"])
def test_mutating_git_refuses_unsupported_inputs_instead_of_disabling_them(tmp_path, monkeypatch, unsupported):
    from harness.git_mutation import GitMutationError, commit_tree

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.com")
    (tmp_path / "a").write_text("a\n")
    git("add", "a")
    git("commit", "-qm", "base")
    parent, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    if unsupported == "hook":
        hook = tmp_path / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n")
        hook.chmod(0o755)
    elif unsupported == "signing":
        git("config", "commit.gpgSign", "true")
    else:
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    identity = {f"GIT_{role}_{field}": value for role in ("AUTHOR", "COMMITTER")
                for field, value in (("NAME", "Fixture"), ("EMAIL", "fixture@example.com"),
                                     ("DATE", "2026-01-01T00:00:00+00:00"))}
    with pytest.raises(GitMutationError, match="GIT_MUTATION_.*UNSUPPORTED"):
        commit_tree(tmp_path, tree, parent, b"candidate\n", identity)
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    assert git("rev-parse", "HEAD") == parent


def test_candidate_feature_does_not_expand_read_only_git_query_or_publication_journal():
    with pytest.raises(GitQueryError, match="GIT_QUERY_INVALID"):
        _validate(("update-ref", "refs/heads/main", "a" * 40, "b" * 40))
