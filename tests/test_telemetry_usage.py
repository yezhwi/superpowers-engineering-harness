"""Usage snapshots must survive local updates without invented measurements."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from harness.controlplane import save_task
from harness.telemetry import update_telemetry

REPO = Path(__file__).resolve().parents[1]


def make_task(root, task_id="TASK-101"):
    task = {"task": {"id": task_id}, "state": "CREATED", "budget": {"test_runs": 1}}
    root.mkdir(exist_ok=True)
    save_task(root, task)
    return task


def run_cli(root, *args):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        capture_output=True,
        text=True,
        check=False,
    )


def report(root, usage, task_id="TASK-101"):
    path = root / "usage.json"
    path.write_text(json.dumps({"task_id": task_id, "usage": usage}))
    return run_cli(root, "telemetry", "report", "--usage-file", str(path))


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    make_task(tmp_path / ".harness")
    return tmp_path


def test_report_total_only_and_save_task_preserve_usage(repo):
    result = report(repo, {"total_tokens": 123, "source": "runtime", "tool_calls": 7})
    assert result.returncode == 0, result.stderr
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    task["budget"]["test_runs"] = 2
    save_task(repo / ".harness", task)
    data = json.loads((repo / ".harness/telemetry.json").read_text())
    assert data["usage"] == {
        "provider": None,
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": 123,
        "source": "runtime",
        "tool_calls": 7,
        "search_rounds": None,
        "file_reads": None,
    }
    assert data["agent"]["tool_calls"] == 7
    assert data["evidence"]["test_runs"] == 2
    assert data["token_estimate"] is None


def test_update_preserves_existing_host_fields(tmp_path):
    task = make_task(tmp_path)
    path = tmp_path / "telemetry.json"
    data = json.loads(path.read_text())
    data["usage"] = {"total_tokens": 12, "source": "provider"}
    data["agent"]["tool_calls"] = 3
    path.write_text(json.dumps(data))
    update_telemetry(tmp_path, task)
    actual = json.loads(path.read_text())
    assert actual["usage"] == {"total_tokens": 12, "source": "provider"}
    assert actual["agent"]["tool_calls"] == 3


def test_reports_are_idempotent_snapshots_and_clear_omitted_fields(repo):
    usage = {
        "input_tokens": 10,
        "output_tokens": 20,
        "total_tokens": 30,
        "source": "provider",
        "provider": "example",
        "tool_calls": 4,
    }
    assert report(repo, usage).returncode == 0
    path = repo / ".harness/telemetry.json"
    before = path.read_bytes()
    assert report(repo, usage).returncode == 0
    assert path.read_bytes() == before
    assert report(repo, {"search_rounds": 2}).returncode == 0
    data = json.loads(path.read_text())
    assert data["usage"]["total_tokens"] is None
    assert data["usage"]["provider"] is None
    assert data["usage"]["source"] is None
    assert data["agent"]["tool_calls"] is None
    assert data["agent"]["search_rounds"] == 2


@pytest.mark.parametrize(
    "usage",
    [
        {"total_tokens": -1, "source": "runtime"},
        {"tool_calls": True},
        {"file_reads": 1.5},
        {"total_tokens": 10},
        {"total_tokens": 0},
        {"source": "unknown"},
        {"provider": 123},
        {"input_tokens": 1, "output_tokens": 2, "total_tokens": 4, "source": "runtime"},
        {"typo": 1},
        [],
        None,
    ],
)
def test_invalid_usage_leaves_telemetry_unchanged(repo, usage):
    path = repo / ".harness/telemetry.json"
    before = path.read_bytes()
    result = report(repo, usage)
    assert result.returncode == 2
    assert "TELEMETRY_USAGE_INVALID" in result.stderr
    assert path.read_bytes() == before


def test_usage_provider_can_be_injected_into_task_usage_report(repo):
    from harness.telemetry import report_provider_usage

    class Provider:
        def get_usage(self):
            return {
                "provider": "test",
                "model": "unit",
                "input_tokens": 2,
                "output_tokens": 3,
                "total_tokens": 5,
                "tool_calls": 1,
                "search_rounds": 0,
                "file_reads": 0,
                "source": "provider",
            }

    report_provider_usage(repo / ".harness", "TASK-101", Provider())
    data = json.loads((repo / ".harness/telemetry.json").read_text())
    assert data["usage"]["total_tokens"] == 5
    assert data["usage"]["source"] == "provider"


def test_zero_tokens_and_estimated_source_are_not_missing(repo):
    assert report(repo, {"total_tokens": 0, "source": "estimated"}).returncode == 0
    data = json.loads((repo / ".harness/telemetry.json").read_text())
    assert data["usage"]["total_tokens"] == 0
    assert data["usage"]["source"] == "estimated"


def test_wrong_task_is_rejected_and_new_task_does_not_inherit(repo):
    assert report(repo, {"total_tokens": 9, "source": "runtime"}).returncode == 0
    path = repo / ".harness/telemetry.json"
    before = path.read_bytes()
    result = report(repo, {}, task_id="TASK-999")
    assert result.returncode == 2
    assert "TELEMETRY_TASK_MISMATCH" in result.stderr
    assert path.read_bytes() == before
    make_task(repo / ".harness", "TASK-102")
    actual = json.loads(path.read_text())
    assert actual["usage"] is None
    assert actual["agent"]["tool_calls"] is None
    assert actual["harness_command_calls"] == 1


def test_subdirectory_usage_file_is_resolved_before_cli_chdir(repo):
    sub = repo / "sub"
    sub.mkdir()
    (sub / "usage.json").write_text(
        json.dumps(
            {
                "task_id": "TASK-101",
                "usage": {"total_tokens": 42, "source": "runtime"},
            }
        )
    )
    result = run_cli(sub, "telemetry", "report", "--usage-file", "usage.json")
    assert result.returncode == 0, result.stderr
    data = json.loads((repo / ".harness/telemetry.json").read_text())
    assert data["usage"]["total_tokens"] == 42


@pytest.mark.parametrize(
    "content", ["[", "[]", "{}", "usage: {}", "task_id: TASK-101\nusage: [x]"]
)
def test_malformed_usage_document_is_rejected_without_mutation(repo, content):
    path = repo / "input.yaml"
    path.write_text(content)
    before = (repo / ".harness/telemetry.json").read_bytes()
    result = run_cli(repo, "telemetry", "report", "--usage-file", str(path))
    assert result.returncode == 2
    assert "TELEMETRY_USAGE_INVALID" in result.stderr
    assert "Traceback" not in result.stderr
    assert (repo / ".harness/telemetry.json").read_bytes() == before


def test_report_without_task_does_not_create_state(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    result = report(tmp_path, {})
    assert result.returncode == 2
    assert "INVALID_HARNESS_STATE" in result.stderr
    assert not (tmp_path / ".harness").exists()


def test_null_task_id_supports_local_facts_but_not_host_ingest(repo):
    make_task(repo / ".harness", None)
    data = json.loads((repo / ".harness/telemetry.json").read_text())
    assert data["usage"] is None
    result = report(repo, {"tool_calls": 2})
    assert result.returncode == 2
    assert "INVALID_HARNESS_STATE" in result.stderr


def test_first_report_without_previous_telemetry_does_not_count_local_command(repo):
    path = repo / ".harness/telemetry.json"
    path.unlink()
    assert report(repo, {"file_reads": 3}).returncode == 0
    data = json.loads(path.read_text())
    assert data["harness_command_calls"] == 0
    assert data["evidence"]["test_runs"] == 1
    assert data["usage"]["file_reads"] == 3


def test_failed_publication_preserves_previous_data_and_releases_lock(
    tmp_path, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor

    from harness import telemetry

    task = make_task(tmp_path)
    path = tmp_path / "telemetry.json"
    before = path.read_bytes()
    original = telemetry.atomic_write

    def fail(path, content):
        raise OSError("injected telemetry publication failure")

    monkeypatch.setattr(telemetry, "atomic_write", fail)
    with pytest.raises(OSError, match="injected telemetry publication failure"):
        telemetry.report_usage(tmp_path, {"task_id": "TASK-101", "usage": {}})
    assert path.read_bytes() == before
    monkeypatch.setattr(telemetry, "atomic_write", original)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(update_telemetry, tmp_path, task).result(timeout=5)
    assert json.loads(path.read_text())["harness_command_calls"] == 2


def test_unreported_usage_is_null(tmp_path):
    task = make_task(tmp_path)
    assert update_telemetry(tmp_path, task)["usage"] is None


def test_stale_local_update_cannot_overwrite_new_task_usage(tmp_path):
    from harness import telemetry

    old = make_task(tmp_path)
    make_task(tmp_path, "TASK-102")
    path = tmp_path / "telemetry.json"
    before = path.read_bytes()
    with pytest.raises(telemetry.TelemetryError, match="TELEMETRY_TASK_MISMATCH"):
        update_telemetry(tmp_path, old)
    assert path.read_bytes() == before


def test_replacement_preserves_usage_reported_after_staging(tmp_path):
    from harness import telemetry
    from harness.task_replacement import publish_replacement, replacement_workspace

    root = tmp_path / ".harness"
    make_task(root)
    staged = replacement_workspace(root)
    telemetry.report_usage(root, {"task_id": "TASK-101", "usage": {"tool_calls": 7}})
    publish_replacement(root, staged)
    data = json.loads((root / "telemetry.json").read_text())
    assert data["usage"]["tool_calls"] == 7


def test_report_and_local_update_serialize_read_modify_write(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event

    from harness import telemetry

    task = make_task(tmp_path)
    entered, release, update_started = Event(), Event(), Event()
    original = telemetry.atomic_write

    def pause_report(path, content):
        # Pause actual report at publication, after it read the old local facts.
        if (json.loads(content).get("usage") or {}).get("tool_calls") == 7:
            entered.set()
            assert release.wait(5)
        original(path, content)

    monkeypatch.setattr(telemetry, "atomic_write", pause_report)

    def local_update():
        update_started.set()
        update_telemetry(tmp_path, task)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reported = pool.submit(
            telemetry.report_usage,
            tmp_path,
            {"task_id": "TASK-101", "usage": {"tool_calls": 7}},
        )
        try:
            assert entered.wait(5)
            updated = pool.submit(local_update)
            assert update_started.wait(5)
            # Writer must not complete while report holds its RMW boundary.
            with pytest.raises(TimeoutError):
                updated.result(timeout=0.2)
        finally:
            release.set()
        reported.result(timeout=5)
        updated.result(timeout=5)
    data = json.loads((tmp_path / "telemetry.json").read_text())
    assert data["usage"]["tool_calls"] == 7
    assert data["harness_command_calls"] == 2


def test_queued_report_rechecks_identity_after_directory_replacement(tmp_path):
    from harness.task_replacement import publish_replacement, replacement_workspace
    from harness.telemetry_lock import telemetry_lock

    root = tmp_path / ".harness"
    make_task(root)
    staged = replacement_workspace(root)
    make_task(staged, "TASK-102")
    script = """
from pathlib import Path
from harness.telemetry import report_usage, TelemetryError
import sys
print("ready", flush=True)
try:
    report_usage(Path(sys.argv[1]), {"task_id": "TASK-101", "usage": {"tool_calls": 9}})
except TelemetryError as exc:
    print(str(exc), flush=True)
    sys.exit(2)
"""
    with telemetry_lock(root):
        child = subprocess.Popen(
            [sys.executable, "-c", script, str(root)],
            env={**os.environ, "PYTHONPATH": str(REPO / "src")},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert child.stdout.readline().strip() == "ready"
            with pytest.raises(subprocess.TimeoutExpired):
                child.wait(timeout=0.2)
            publish_replacement(root, staged)
        except BaseException:
            child.kill()
            child.communicate()
            raise
    out, err = child.communicate(timeout=5)
    assert child.returncode == 2, err
    assert "TELEMETRY_TASK_MISMATCH" in out
    data = json.loads((root / "telemetry.json").read_text())
    assert data["task_id"] == "TASK-102"
    assert data["usage"] is None


def test_concurrent_process_updates_do_not_lose_local_counts(tmp_path):
    make_task(tmp_path)
    from harness.telemetry import report_usage

    report_usage(
        tmp_path,
        {"task_id": "TASK-101", "usage": {"total_tokens": 123, "source": "runtime"}},
    )
    script = """
from pathlib import Path
import sys, yaml
from harness.telemetry import update_telemetry
root = Path(sys.argv[1])
task = yaml.safe_load((root / "current-task.yaml").read_text())
for _ in range(10):
    update_telemetry(root, task)
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path)],
            env={**os.environ, "PYTHONPATH": str(REPO / "src")},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    try:
        for child in children:
            _, err = child.communicate(timeout=10)
            assert child.returncode == 0, err
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate()
    data = json.loads((tmp_path / "telemetry.json").read_text())
    assert data["harness_command_calls"] == 41
    assert data["usage"]["total_tokens"] == 123
