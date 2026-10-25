"""Task replacement must retain opaque probes without reading or copying them."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from harness import controlplane, task_replacement
from test_cli_task_recovery import make_repo, run_cli, set_task_state


def identity(path):
    info = path.lstat()
    return info.st_dev, info.st_ino, info.st_mode


def probe_tree(harness, name="acceptance-probes"):
    probe = harness / name
    nested = probe / "example" / "fifo-input" / ".harness"
    nested.mkdir(parents=True)
    fifo = nested / "artifact.yaml"
    os.mkfifo(fifo)
    (probe / "regular.txt").write_text("opaque fixture bytes\n")
    (probe / "outside-link").symlink_to(harness.parent / "unavailable")
    return probe, fifo


def retained_root(harness):
    roots = list((harness / ".publication-retained").glob("task-replacement-*/previous"))
    assert len(roots) == 1
    return roots[0]


def bare_harness(tmp_path):
    harness = tmp_path / ".harness"
    harness.mkdir()
    (harness / "current-task.yaml").write_text("old task\n")
    return harness


@pytest.mark.parametrize("opaque", ["acceptance-probes", "acceptance-artifacts"])
def test_replacement_copy_never_enters_root_opaque_probes(tmp_path, monkeypatch, opaque):
    harness = bare_harness(tmp_path)
    probe, fifo = probe_tree(harness, opaque)
    before = identity(fifo)
    original_copytree = shutil.copytree

    def no_probe_copy(source, *args, **kwargs):
        assert not Path(source).is_relative_to(probe), "copy traversed opaque probe tree"
        return original_copytree(source, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", no_probe_copy)
    staged = task_replacement.replacement_workspace(harness)
    assert not (staged / opaque).exists()
    assert (staged / "current-task.yaml").read_text() == "old task\n"
    assert identity(fifo) == before


@pytest.mark.parametrize("relative", [
    "requirements.yaml", "evidence/input.pipe", "evidence/acceptance-probes/input.pipe",
    "evidence/acceptance-artifacts/input.pipe",
])
def test_canonical_and_nested_special_files_still_refuse(tmp_path, relative):
    harness = bare_harness(tmp_path)
    fifo = harness / relative
    fifo.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(fifo)
    before = identity(fifo)
    with pytest.raises(shutil.Error, match="named pipe"):
        task_replacement.replacement_workspace(harness)
    assert identity(fifo) == before
    assert (harness / "current-task.yaml").read_text() == "old task\n"
    assert not list(tmp_path.glob("..harness.replacement-*"))


@pytest.mark.parametrize("opaque", ["acceptance-probes", "acceptance-artifacts"])
def test_publish_retains_original_probe_directory_and_child_inodes(tmp_path, capsys, opaque):
    harness = bare_harness(tmp_path)
    probe, fifo = probe_tree(harness, opaque)
    relative = fifo.relative_to(probe)
    original = {name: identity(probe / name) for name in (".", str(relative), "regular.txt", "outside-link")}
    staged = task_replacement.replacement_workspace(harness)
    (staged / "current-task.yaml").write_text("new task\n")
    task_replacement._publish_replacement(harness, staged)
    old = retained_root(harness)
    kept = old / opaque
    assert {name: identity(kept / name) for name in original} == original
    assert stat.S_ISFIFO((kept / relative).lstat().st_mode)
    assert (kept / "regular.txt").read_text() == "opaque fixture bytes\n"
    assert (kept / "outside-link").is_symlink()
    assert not (harness / opaque).exists()
    assert (harness / "current-task.yaml").read_text() == "new task\n"
    assert str(old.relative_to(harness)) in capsys.readouterr().err


@pytest.mark.parametrize("opaque", ["acceptance-probes", "acceptance-artifacts"])
def test_failed_install_restores_original_probe_tree(tmp_path, monkeypatch, opaque):
    harness = bare_harness(tmp_path)
    probe, fifo = probe_tree(harness, opaque)
    before = identity(fifo)
    staged = task_replacement.replacement_workspace(harness)
    original_replace = Path.replace

    def fail_install(source, destination):
        if source == staged:
            raise OSError("injected install failure")
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", fail_install)
    with pytest.raises(OSError, match="injected install failure"):
        task_replacement._publish_replacement(harness, staged)
    assert identity(fifo) == before
    assert (harness / "current-task.yaml").read_text() == "old task\n"
    assert not harness.with_name("..harness.backup").exists()


def test_retention_diagnostic_failure_does_not_fail_publication(tmp_path, monkeypatch):
    harness = bare_harness(tmp_path)
    probe, fifo = probe_tree(harness)
    relative = fifo.relative_to(probe)
    before = identity(fifo)
    staged = task_replacement.replacement_workspace(harness)

    class ClosedSink:
        def write(self, text):
            raise OSError("closed diagnostic sink")

    import sys
    monkeypatch.setattr(sys, "stderr", ClosedSink())
    task_replacement._publish_replacement(harness, staged)
    assert identity(retained_root(harness) / "acceptance-probes" / relative) == before


def committed_repo(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run([
        "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "fixture",
    ], cwd=repo, check=True)
    return repo


@pytest.mark.parametrize("opaque", ["acceptance-probes", "acceptance-artifacts"])
@pytest.mark.parametrize("operation", ["new", "recover", "escalate"])
def test_native_task_commands_preserve_opaque_fifo(tmp_path, operation, opaque):
    repo = committed_repo(tmp_path)
    harness = repo / ".harness"
    if operation == "escalate":
        classified = run_cli(repo, "task", "classify", "--level", "Q1", "--scope", "low",
                             "--contract", "none", "--data", "none", "--authorization", "none",
                             "--security", "none", "--concurrency", "none", "--deployment", "none")
        assert classified.returncode == 0, classified.stderr
        arguments = ("task", "escalate", "--level", "Q2", "--reason", "fixture")
    else:
        set_task_state(repo, "DONE" if operation == "new" else "IMPLEMENTING")
        arguments = ("task", operation, "TASK-005")
        if operation == "recover":
            arguments += ("--reason", "fixture")
    probe, fifo = probe_tree(harness, opaque)
    relative = fifo.relative_to(probe)
    before = identity(fifo)
    result = run_cli(repo, *arguments)
    assert result.returncode == 0, result.stdout + result.stderr
    kept = retained_root(harness)
    assert identity(kept / opaque / relative) == before
    assert str(kept.relative_to(harness)) in result.stderr
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    if operation == "escalate":
        assert task["risk"]["level"] == "Q2"
    else:
        assert task["task"]["id"] == "TASK-005"


def test_native_new_retention_failure_keeps_original_at_backup(tmp_path, monkeypatch, capsys):
    repo = committed_repo(tmp_path)
    set_task_state(repo, "DONE")
    harness = repo / ".harness"
    probe, fifo = probe_tree(harness)
    relative = fifo.relative_to(harness)
    before = identity(fifo)
    monkeypatch.chdir(repo)

    def fail_retention(*args):
        raise OSError("injected retention failure")

    monkeypatch.setattr(task_replacement, "_retain_replaced_harness", fail_retention)
    assert controlplane.cmd_task_new("TASK-005", "fixture") == 2
    output = capsys.readouterr()
    assert "TASK_REPLACEMENT_FAILED" in output.err
    assert "OK: archived" not in output.out
    backup = harness.with_name("..harness.backup")
    assert identity(backup / relative) == before
    assert yaml.safe_load((harness / "current-task.yaml").read_text())["task"]["id"] == "TASK-005"
