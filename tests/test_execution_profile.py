"""Real pytest config/cwd probes; config shim is NOT xdist execution qualification."""
import shlex
import sys

import pytest

from harness.execution_capture import run
from harness.execution_proof import valid


@pytest.mark.parametrize("mode", ["numprocesses", "dist", "tx", "workerinput", "serial"])
@pytest.mark.parametrize("source", ["environment", "ini"])
def test_actual_worker_configuration_cannot_qualify(tmp_path, monkeypatch, mode, source):
    (tmp_path / "test_target.py").write_text("def test_target():\n    assert True\n")
    # Register only config options to exercise the real reporter's config boundary.
    # No worker launch, xdist install or claim that this emulates xdist runtime.
    (tmp_path / "conftest.py").write_text(
        "def pytest_addoption(parser):\n"
        "    parser.addoption('--numprocesses', default=None)\n"
        "    parser.addoption('--dist', default='no')\n"
        "    parser.addoption('--tx', action='append', default=[])\n"
        + ("def pytest_configure(config):\n    config.workerinput = {}\n" if mode == "workerinput" else "")
    )
    option = {"numprocesses": "--numprocesses=2", "dist": "--dist=load",
              "tx": "--tx=ssh=host", "workerinput": "", "serial": ""}[mode]
    if source == "environment":
        monkeypatch.setenv("PYTEST_ADDOPTS", option)
    else:
        monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
        (tmp_path / "pytest.ini").write_text(f"[pytest]\naddopts = {option}\n")
    monkeypatch.chdir(tmp_path)
    command = shlex.join([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_target.py"])
    result, proof = run(command, 30, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert valid({"exit_code": 0, "test_execution": proof, "covered_tests": ["test_target.py"]}, True) is (mode == "serial")


@pytest.mark.parametrize("wrapper", ["cd backend && env MODE=red {pytest}",
                                     "env MODE=red sh -c {quoted_pytest}"])
def test_transparent_combinations_keep_real_proof(tmp_path, monkeypatch, wrapper):
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "test_target.py").write_text("def test_target():\n    assert True\n")
    monkeypatch.chdir(tmp_path)
    args = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if wrapper.startswith("cd"):
        args += ["test_target.py", "--rootdir=.."]
    else:
        args += ["backend/test_target.py", "--rootdir=."]
    command = shlex.join(args)
    result, proof = run(wrapper.format(pytest=command, quoted_pytest=shlex.quote(command)), 30, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert valid({"exit_code": 0, "test_execution": proof, "covered_tests": ["backend/test_target.py"]}, True)
