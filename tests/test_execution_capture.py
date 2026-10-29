"""Synthetic report transport counterexamples; native proof lives in execution_integrity."""
import json
import os
import subprocess
from pathlib import Path

import pytest
from evidence_factory import synthetic_execution

from harness import execution_capture


@pytest.mark.parametrize("variant", [
    "valid", "missing", "symlink", "fifo", "oversized", "invalid_json", "nonce",
    "extra", "root_type", "relative_root", "nodes_type", "node_type", "outside",
    "errors_type", "assertion_without_failure",
])
def test_report_transport_is_bounded_and_fail_closed(tmp_path, monkeypatch, variant):
    repository = tmp_path / "repo"
    repository.mkdir()

    def child(command, **kwargs):
        environment = kwargs["env"]
        directory = Path(environment["HARNESS_PYTEST_REPORT_DIR"])
        path = directory / "report.json"
        report = synthetic_execution(["tests/test_x.py::test_x"])["runs"][0]
        report.update(root=str(repository), nonce=environment["HARNESS_PYTEST_REPORT_NONCE"])
        if variant == "missing":
            pass
        elif variant == "symlink":
            external = tmp_path / "external.json"
            external.write_text(json.dumps(report))
            path.symlink_to(external)
        elif variant == "fifo":
            os.mkfifo(path)
        elif variant == "oversized":
            with path.open("wb") as stream:
                stream.seek(execution_capture.LIMIT)
                stream.write(b"x")
        elif variant == "invalid_json":
            path.write_text("{broken")
        else:
            if variant == "nonce":
                report["nonce"] = "wrong"
            elif variant == "extra":
                report["unrecognized"] = True
            elif variant == "root_type":
                report["root"] = []
            elif variant == "relative_root":
                report["root"] = "."
            elif variant == "nodes_type":
                report["collected"] = None
            elif variant == "node_type":
                report["collected"] = [{}]
            elif variant == "outside":
                report["collected"] = ["../outside.py::test_x"]
            elif variant == "errors_type":
                report["errors"] = True
            elif variant == "assertion_without_failure":
                report["assertion_failures"] = report["passed"]
            path.write_text(json.dumps(report))
        return subprocess.CompletedProcess(command, 0, "measured output", "")

    monkeypatch.setattr(execution_capture, "run_command", child)
    result, proof = execution_capture.run("python -m pytest tests/test_x.py", 5, repository)
    assert result.stdout == "measured output"
    assert (proof is not None) is (variant == "valid")


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group lifecycle")
@pytest.mark.parametrize("entry", ["reporter", "measurement"])
@pytest.mark.parametrize("failure", ["timeout", "cancel"])
@pytest.mark.parametrize("ignore_term", [False, True])
@pytest.mark.parametrize("shell_waits", [False, True])
def test_failed_command_stops_owned_descendants(tmp_path, monkeypatch, entry, failure, ignore_term, shell_waits):
    import shlex
    import signal
    import sys
    import time

    from harness import collect_evidence

    repo = tmp_path / "repo"
    repo.mkdir()
    activity = tmp_path / "activity"
    ready = tmp_path / "ready"
    child = repo / "child.py"
    child.write_text(
        "import os, signal, time\nfrom pathlib import Path\n"
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if ignore_term else "")
        + f"Path({str(ready)!r}).write_text(str(os.getpid()))\n"
        + "print('started', flush=True)\n"
        + "while True:\n"
        + f"    with Path({str(activity)!r}).open('a') as stream: stream.write('x')\n"
        + "    time.sleep(.02)\n"
    )
    for args in (["init", "-q"], ["add", "."],
                 ["-c", "user.name=Review", "-c", "user.email=review@example.invalid", "commit", "-qm", "baseline"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    monkeypatch.chdir(repo)
    # Exercise both a waiting shell and shell exec optimization. TERM-resistant
    # exec also requires escalation when the root itself exceeds TERM grace.
    command = shlex.join([sys.executable, "-u", str(child)]) + ("; :" if shell_waits else "")
    if failure == "cancel":
        communicate = subprocess.Popen.communicate

        def interrupt(process, *args, **kwargs):
            if process.args != command:
                return communicate(process, *args, **kwargs)
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            assert ready.exists(), "child did not reach execution"
            raise KeyboardInterrupt()
        monkeypatch.setattr(subprocess.Popen, "communicate", interrupt)
    try:
        if entry == "measurement":
            record = collect_evidence._collect("build", collect_evidence._TrustedLocalCommand(command),
                                               timeout_seconds=.3)
            assert record["error"] == ("EVIDENCE_COMMAND_TIMEOUT" if failure == "timeout" else "EVIDENCE_COMMAND_CANCELLED")
            if failure == "timeout":
                assert "started" in record["stdout_tail"]
        else:
            with pytest.raises(subprocess.TimeoutExpired if failure == "timeout" else KeyboardInterrupt):
                execution_capture.run(command, .3, repo)
        assert ready.exists(), "child did not reach execution"
        before = activity.read_bytes()
        time.sleep(.15)
        assert activity.read_bytes() == before, "descendant continued writing after failure returned"
    finally:
        if ready.exists():
            try:
                os.kill(int(ready.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("cleanup_error", [OSError("cleanup failed"), subprocess.TimeoutExpired("cleanup", 1)])
def test_cleanup_failure_does_not_replace_primary_timeout(tmp_path, monkeypatch, cleanup_error):
    import shlex
    import sys

    stop = execution_capture._stop_command

    def fail_after_stop(process):
        stop(process)
        raise cleanup_error

    monkeypatch.setattr(execution_capture, "_stop_command", fail_after_stop)
    command = shlex.join([sys.executable, "-c", "import time; time.sleep(10)"])
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        execution_capture.run_command(command, timeout=.1)
    assert raised.value.cmd == command
    assert raised.value.timeout == .1


def test_command_runner_keeps_nonzero_measurement_and_output():
    result = execution_capture.run_command("printf out; printf err >&2; exit 7", timeout=5)
    assert (result.returncode, result.stdout, result.stderr) == (7, "out", "err")
