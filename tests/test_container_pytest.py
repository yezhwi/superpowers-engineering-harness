"""Container pytest admission. Host pytest is not a substitute receipt."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness.collect_evidence import _TrustedLocalCommand, _collect
from harness.container_pytest import Attempt, ContainerRefusal, admit, classify, interpret, parse_maps
from harness.execution_capture import supported_command
from harness.execution_proof import valid

ROOT = Path(__file__).resolve().parents[1]
REPORTER = ROOT / "src" / "harness" / "container_reporter.py"
NODE = "tests/test_sample.py::test_one"
FP = "sha256:" + "a" * 64
FP2 = "sha256:" + "b" * 64


def _attempt(**overrides):
    values = dict(
        run_id="run-1", attempt="attempt-1", command="pytest tests/test_sample.py",
        target={"workload": "deploy/app"}, before_fingerprint=FP, after_fingerprint=FP,
        path_map=parse_maps(("/workspace=",)),
    )
    values.update(overrides)
    return Attempt(**values)


def _report(**overrides):
    document = {
        "schema": "container-pytest/v1",
        "run_id": "run-1",
        "attempt": "attempt-1",
        "command": "pytest tests/test_sample.py",
        "exit_code": 0,
        "errors": 0,
        "collected": ["/workspace/tests/test_sample.py::test_one"],
        "passed": ["/workspace/tests/test_sample.py::test_one"],
        "failed": [],
        "skipped": [],
        "assertion_failures": [],
        "target": {"workload": "deploy/app"},
        "source_fingerprint": FP,
    }
    document.update(overrides)
    return document


def _record(proof, exit_code=0):
    return {"exit_code": exit_code, "covered_tests": [NODE], "test_execution": proof}


def test_kubectl_text_is_not_native_pytest():
    assert supported_command("kubectl exec deploy/app -- pytest tests/test_sample.py") is False


def test_basename_map_is_rejected():
    with pytest.raises(ContainerRefusal) as caught:
        parse_maps(("test_sample.py=tests/test_sample.py",))
    assert caught.value.code == "CONTAINER_PATH_MAP_MISMATCH"


def test_passed_red_skipped_empty_and_parametrized_reports_stay_distinct():
    passed = admit(_report(), _attempt())
    assert classify(passed["runs"][0]) == "passed"
    assert valid(_record(passed), True)

    red = admit(_report(exit_code=1, passed=[], failed=["/workspace/" + NODE],
                        assertion_failures=["/workspace/" + NODE]), _attempt())
    assert classify(red["runs"][0]) == "red"
    assert valid(_record(red, 1), False) and not valid(_record(red, 1), True)

    skipped = admit(_report(exit_code=0, passed=[], skipped=["/workspace/" + NODE]), _attempt())
    assert classify(skipped["runs"][0]) == "skipped"
    assert not valid(_record(skipped), True)

    empty = admit(_report(exit_code=5, collected=[], passed=[]), _attempt())
    assert classify(empty["runs"][0]) == "empty"
    assert not valid(_record(empty, 5), True)

    left = "/workspace/tests/test_sample.py::test_values[1]"
    right = "/workspace/tests/test_sample.py::test_values[2]"
    parametrized = admit(_report(collected=[left, right], passed=[left, right]), _attempt())
    assert parametrized["runs"][0]["passed"] == [
        "tests/test_sample.py::test_values[1]", "tests/test_sample.py::test_values[2]",
    ]
    assert "result" not in parametrized


def test_collect_error_is_not_success():
    proof = admit(_report(exit_code=2, errors=1, collected=[], passed=[]), _attempt())
    assert classify(proof["runs"][0]) == "collect_error"
    assert not valid(_record(proof, 2), True)


@pytest.mark.parametrize(("change", "code"), [
    ({"run_id": "old-run"}, "CONTAINER_RUN_ID_MISMATCH"),
    ({"attempt": "old-attempt"}, "CONTAINER_REPORT_STALE"),
    ({"source_fingerprint": FP2}, "CONTAINER_SOURCE_DRIFT"),
    ({"target": {"workload": "deploy/other"}}, "CONTAINER_TARGET_MISMATCH"),
    ({"collected": ["/other/tests/test_sample.py::test_one"],
      "passed": ["/other/tests/test_sample.py::test_one"]}, "CONTAINER_PATH_MAP_MISMATCH"),
])
def test_bad_report_cannot_pass(change, code):
    with pytest.raises(ContainerRefusal) as caught:
        admit(_report(**change), _attempt())
    assert caught.value.code == code


def test_duplicate_and_process_failures_have_no_proof():
    with pytest.raises(ContainerRefusal) as caught:
        admit(_report(), _attempt(accepted_attempts=frozenset({"attempt-1"})))
    assert caught.value.code == "CONTAINER_REPORT_DUPLICATE"
    assert interpret(b"", 1, _attempt())[1] == "CONTAINER_PROCESS_EXIT"
    assert interpret(b"", 0, _attempt())[1] == "CONTAINER_REPORT_MISSING"
    assert interpret(b"{", 1, _attempt())[1] == "CONTAINER_REPORT_TRANSFER_FAILED"
    assert interpret(b"", None, _attempt(), timed_out=True)[1] == "CONTAINER_REPORT_TIMEOUT"


def test_admit_does_not_rewrite_an_old_receipt(tmp_path):
    receipt = tmp_path / "old.json"
    receipt.write_text('{"exit_code": 1, "test_execution": {"schema": "pytest-execution/v1"}}')
    before = receipt.read_bytes()
    admit(_report(), _attempt())
    assert receipt.read_bytes() == before


def _run_reporter(root: Path, args, filename, source):
    tests = root / "tests"
    tests.mkdir(parents=True)
    (tests / filename).write_text(source)
    env = {
        "HARNESS_RUN_ID": "run-1",
        "HARNESS_ATTEMPT": "attempt-1",
        "HARNESS_COMMAND": "pytest " + " ".join(args),
        "HARNESS_TARGET": json.dumps({"workload": "deploy/app"}, separators=(",", ":")),
        "HARNESS_SOURCE_FINGERPRINT": FP,
        "HARNESS_CONTAINER_ROOT": str(root),
        "HARNESS_PYTEST_ARGS": json.dumps(args),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [sys.executable, str(REPORTER)], cwd=root, env=env, capture_output=True, text=True, check=False,
    )
    return completed.returncode, json.loads(completed.stdout)


def test_reporter_distinguishes_live_outcomes(tmp_path):
    code, passed = _run_reporter(
        tmp_path / "pass", ["tests/test_sample.py"], "test_sample.py", "def test_one():\n    assert True\n",
    )
    assert code == 0 and classify(_mapped(passed, tmp_path / "pass")) == "passed"

    code, red = _run_reporter(
        tmp_path / "red", ["tests/test_sample.py"], "test_sample.py", "def test_one():\n    assert False\n",
    )
    assert code == 1 and classify(_mapped(red, tmp_path / "red")) == "red"

    code, skipped = _run_reporter(
        tmp_path / "skip", ["tests/test_sample.py"], "test_sample.py",
        "import pytest\n\ndef test_one():\n    pytest.skip('later')\n",
    )
    assert classify(_mapped(skipped, tmp_path / "skip")) == "skipped"

    code, empty = _run_reporter(
        tmp_path / "empty", ["-k", "absent", "tests/test_sample.py"], "test_sample.py",
        "def test_one():\n    assert True\n",
    )
    assert code != 0 and classify(_mapped(empty, tmp_path / "empty")) == "empty"

    code, params = _run_reporter(
        tmp_path / "params", ["tests/test_sample.py"], "test_sample.py",
        "import pytest\n\n@pytest.mark.parametrize('value', [1, 2])\n"
        "def test_values(value):\n    assert value\n",
    )
    assert [node.split("::", 1)[1] for node in _mapped(params, tmp_path / "params")["passed"]] == [
        "test_values[1]", "test_values[2]",
    ]

    code, broken = _run_reporter(
        tmp_path / "import", ["tests/test_sample.py"], "test_sample.py",
        "import harness_container_missing_module\n",
    )
    assert code != 0 and classify(_mapped(broken, tmp_path / "import")) == "collect_error"


def _mapped(report, root: Path):
    report = dict(report)
    report["command"] = "pytest tests/test_sample.py"
    proof = admit(report, _attempt(command=report["command"], path_map=parse_maps((f"{root}=",))))
    return proof["runs"][0]


def test_container_collection_does_not_run_host_pytest(monkeypatch):
    fingerprints = iter((FP, FP))

    def snapshot():
        return type("S", (), {"head": "a" * 40, "fingerprint": next(fingerprints)})()

    def fail_host(*args, **kwargs):
        raise AssertionError("host pytest or shell ran")

    monkeypatch.setattr("harness.collect_evidence.git_head", lambda: "a" * 40)
    monkeypatch.setattr("harness.collect_evidence.snapshot", snapshot)
    monkeypatch.setattr("harness.collect_evidence.execution_capture.run", fail_host)
    monkeypatch.setattr("harness.collect_evidence.subprocess.run", fail_host)

    def spawn(argv, reporter):
        assert Path(argv[0]).name == "kubectl"
        assert "pytest" not in argv[0]
        env = dict(arg.split("=", 1) for arg in argv if arg.startswith("HARNESS_"))
        report = _report(
            run_id=env["HARNESS_RUN_ID"], attempt=env["HARNESS_ATTEMPT"],
            command=env["HARNESS_COMMAND"], target=json.loads(env["HARNESS_TARGET"]),
            source_fingerprint=env["HARNESS_SOURCE_FINGERPRINT"],
        )
        assert b"pytest" in reporter
        return 0, json.dumps(report).encode(), b""

    evidence = _collect(
        "unit_test", _TrustedLocalCommand("kubectl exec deploy/app -- pytest tests/test_sample.py"),
        covered_tests=(NODE,), container_maps=("/workspace=",), container_spawn=spawn,
    )
    assert evidence["test_execution"]["runs"][0]["passed"] == [NODE]
    assert evidence["container_receipt"]["target"] == {"workload": "deploy/app"}
    assert "error" not in evidence


def test_local_pytest_cannot_use_the_container_adapter(monkeypatch):
    monkeypatch.setattr("harness.collect_evidence.git_head", lambda: "a" * 40)
    monkeypatch.setattr(
        "harness.collect_evidence.snapshot",
        lambda: type("S", (), {"head": "a" * 40, "fingerprint": FP})(),
    )
    monkeypatch.setattr(
        "harness.collect_evidence.execution_capture.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("host capture")),
    )
    evidence = _collect(
        "unit_test", _TrustedLocalCommand("pytest tests/test_sample.py"),
        covered_tests=(NODE,), container_maps=("/workspace=",),
        container_spawn=lambda *args: (_ for _ in ()).throw(AssertionError("spawn")),
    )
    assert evidence["error"] == "CONTAINER_TRANSPORT_REQUIRED"
    assert "test_execution" not in evidence
