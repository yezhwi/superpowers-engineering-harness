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

    monkeypatch.setattr(execution_capture.subprocess, "run", child)
    result, proof = execution_capture.run("python -m pytest tests/test_x.py", 5, repository)
    assert result.stdout == "measured output"
    assert (proof is not None) is (variant == "valid")
