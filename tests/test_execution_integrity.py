"""Real-child counterexamples for test coverage and RED proof admission."""
import json
import sys
from copy import deepcopy

import pytest
from test_cli_task_recovery import run_cli
from test_task_replacement import committed_repo

from harness import workspace
from harness.evidence_validator import EvidenceValidationError, validate_evidence


def collect(tmp_path, monkeypatch, body, selector, options="", phase=None, kind="unit_test", cover=True,
            prefix=""):
    repo = committed_repo(tmp_path)
    directory = repo / "tests"
    directory.mkdir()
    (directory / "test_actual.py").write_text(body)
    command = f"{prefix}{sys.executable} -B -m pytest -q -p no:cacheprovider tests/test_actual.py {options}"
    arguments = ["evidence", "run", "--type", kind, "--command", command]
    if kind == "custom":
        arguments += ["--finding", "FND-001", "--test", selector]
    elif cover:
        arguments += ["--covered-test", selector]
    if phase:
        arguments += ["--phase", phase]
    result = run_cli(repo, *arguments)
    assert result.returncode == 0, result.stdout + result.stderr
    receipts = list((repo / ".harness/evidence").glob("*.json"))
    assert len(receipts) == 1
    record = json.loads(receipts[0].read_text())
    monkeypatch.chdir(repo)
    return record, workspace.snapshot(repo)


@pytest.mark.parametrize("target_fails", [False, True])
def test_red_must_fail_declared_target(tmp_path, monkeypatch, target_fails):
    record, snapshot = collect(tmp_path, monkeypatch,
        f"def test_required():\n    assert {not target_fails!r}\ndef test_other():\n    assert False\n",
        "tests/test_actual.py::test_required", phase="red")
    if target_fails:
        validate(record, snapshot, False)
    else:
        with pytest.raises(EvidenceValidationError, match="EVIDENCE_TEST_EXECUTION"):
            validate(record, snapshot, False)


def test_red_requires_every_declared_target_not_only_first(tmp_path, monkeypatch):
    record, snapshot = collect(tmp_path, monkeypatch,
        "def test_required():\n    assert False\ndef test_other():\n    assert True\n",
        "tests/test_actual.py::test_required", phase="red")
    validate(record, snapshot, False)
    # Unit projection adds an unsupported claim; original native receipt remains untouched.
    expanded = {**record, "covered_tests": ["tests/test_actual.py::test_required",
                                            "tests/test_actual.py::test_other"]}
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_TEST_EXECUTION"):
        validate(expanded, snapshot, False)


@pytest.mark.parametrize("success", [True, False])
def test_masked_preceding_checker_failure_is_not_test_proof(tmp_path, monkeypatch, success):
    import shlex

    prefix = f"{shlex.quote(sys.executable)} -c 'raise RuntimeError()'; "
    record, snapshot = collect(tmp_path, monkeypatch,
        f"def test_required():\n    assert {success!r}\n", "tests/test_actual.py::test_required",
        prefix=prefix)
    assert record["exit_code"] == (0 if success else 1)  # Preserve actual shell measurement.
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_TEST_EXECUTION"):
        validate(record, snapshot, success)


@pytest.mark.parametrize("prefix,options", [
    ("MODE=red ", ""), ("env MODE=red ", ""),
    ("sh -lc '", "'"), ("cd tests && ", ""),
])
def test_supported_command_wrappers_keep_actual_proof(tmp_path, monkeypatch, prefix, options):
    if prefix == "cd tests && ":
        # Run from a subdirectory while keeping selector canonical at repository root.
        body = "def test_required():\n    assert True\n"
        repo = committed_repo(tmp_path)
        (repo / "tests").mkdir()
        (repo / "tests/test_actual.py").write_text(body)
        command = f"cd tests && {sys.executable} -B -m pytest -q -p no:cacheprovider test_actual.py --rootdir=.."
        result = run_cli(repo, "evidence", "run", "--type", "unit_test", "--covered-test",
                         "tests/test_actual.py::test_required", "--command", command)
        assert result.returncode == 0, result.stdout + result.stderr
        record = json.loads(next((repo / ".harness/evidence").glob("*.json")).read_text())
        monkeypatch.chdir(repo)
        snapshot = workspace.snapshot(repo)
    else:
        record, snapshot = collect(tmp_path, monkeypatch, "def test_required():\n    assert True\n",
                                   "tests/test_actual.py::test_required", prefix=prefix, options=options)
    validate(record, snapshot, True)


@pytest.mark.parametrize("field,value", [
    ("passed", [{}]), ("passed", ["/outside.py::test_x"]),
    ("passed", ["../outside.py::test_x"]), ("passed", ["tests/test_actual.py::missing"]),
    ("passed", ["tests/test_actual.py::test_required"] * 2),
    ("errors", True), ("errors", -1), ("exit_code", True),
    ("skipped", ["tests/test_actual.py::test_required"]),
])
def test_malformed_execution_fails_closed_without_exception(field, value):
    from harness.execution_proof import valid
    node = "tests/test_actual.py::test_required"
    run = {"collected": [node], "passed": [node], "failed": [], "skipped": [],
           "assertion_failures": [], "errors": 0, "exit_code": 0}
    run[field] = value
    assert valid({"exit_code": 0, "test_execution": {"schema": "pytest-execution/v1", "runs": [run]}}, True) is False


@pytest.mark.parametrize("node", [
    "C:/outside.py::test_x", r"tests\test_x.py::test_x", "./test_x.py::test_x",
    "tests/./test_x.py::test_x", "tests//test_x.py::test_x", ".", "tests/test_x.py::",
    "", "tests/\x00test_x.py::test_x",
])
def test_noncanonical_execution_node_is_not_proof(node):
    from harness.execution_proof import valid
    run = {"collected": [node], "passed": [node], "failed": [], "skipped": [],
           "assertion_failures": [], "errors": 0, "exit_code": 0}
    assert valid({"exit_code": 0, "test_execution": {"schema": "pytest-execution/v1", "runs": [run]}}, True) is False


@pytest.mark.parametrize("identifier,selector,accepted", [
    ("one][two", "tests/test_actual.py::test_required", True),
    ("one][two", "tests/test_actual.py::test_required[one][two]", True),
    ("one][two", "tests/test_actual.py::test_required[one]", False),
    ("one]::nested", "tests/test_actual.py::test_required[one]", False),
])
def test_parameterized_target_is_exact_not_a_prefix(tmp_path, monkeypatch, identifier, selector, accepted):
    body = (f"import pytest\n@pytest.mark.parametrize('value', [1], ids=[{identifier!r}])\n"
            "def test_required(value):\n    assert value == 1\n")
    record, snapshot = collect(tmp_path, monkeypatch, body, selector)
    if accepted:
        validate(record, snapshot, True)
    else:
        with pytest.raises(EvidenceValidationError, match="EVIDENCE_TEST_EXECUTION"):
            validate(record, snapshot, True)
        from harness.collect_evidence import record_covers_test
        assert not record_covers_test(record, selector)


@pytest.mark.parametrize("node,target,accepted", [
    ("tests/test_x.py[other].py::test_x", "tests/test_x.py", False),
    ("tests/test_x.py::TestX::test_x", "tests/test_x.py::TestX", True),
    ("tests/test_[x].py::test_x", "tests/test_[x].py", True),
])
def test_file_and_class_targets_keep_node_boundaries(node, target, accepted):
    from evidence_factory import synthetic_execution

    from harness.execution_proof import valid
    record = {"exit_code": 0, "covered_tests": [target], "test_execution": synthetic_execution([node])}
    assert valid(record, True) is accepted


def test_parameter_backslash_is_not_a_path_separator():
    from harness.execution_proof import valid
    node = r"tests/test_x.py::test_x[C:\file]"
    run = {"collected": [node], "passed": [node], "failed": [], "skipped": [],
           "assertion_failures": [], "errors": 0, "exit_code": 0}
    assert valid({"exit_code": 0, "test_execution": {"schema": "pytest-execution/v1", "runs": [run]}}, True)


@pytest.mark.parametrize("extra", [
    {"test": "not a mapping"}, {"test": {}}, {"covered_tests": "not a list"},
    {"covered_tests": [None]}, {"test_execution_error": "TEST_EXECUTION_REPORT_MISSING_OR_INVALID"},
    {"exit_code": False}, {"error": "EVIDENCE_COMMAND_TIMEOUT"},
    {"error_detail": {"code": "EVIDENCE_COMMAND_TIMEOUT", "kind": "timeout", "timeout_seconds": 2}},
])
def test_malformed_subject_and_conflicting_error_are_not_proof(extra):
    from harness.execution_proof import valid
    node = "tests/test_actual.py::test_required"
    run = {"collected": [node], "passed": [node], "failed": [], "skipped": [], "assertion_failures": [], "errors": 0, "exit_code": 0}
    record = {"exit_code": 0, "test_execution": {"schema": "pytest-execution/v1", "runs": [run]}, **extra}
    assert valid(record, True) is False


def test_unbound_custom_finding_closure_is_not_measurement_only(tmp_path, monkeypatch):
    from harness.evidence_validator import validate_finding_closure_evidence
    record, snapshot = collect(tmp_path, monkeypatch, "def test_required():\n    assert True\n",
                               "tests/test_actual.py::test_required")
    raw = {key: value for key, value in record.items()
           if key not in {"test_execution", "covered_tests", "covered_test_cases"}}
    raw["type"] = "custom"
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_TEST_EXECUTION"):
        validate_finding_closure_evidence({"severity": "critical"}, raw, {},
            current_head=snapshot.head, current_workspace=snapshot.fingerprint)


def test_unbound_failed_measurement_is_not_product_red(tmp_path, monkeypatch):
    record, snapshot = collect(tmp_path, monkeypatch, "def test_required():\n    assert False\n",
                               "tests/test_actual.py::test_required")
    raw = {key: value for key, value in record.items()
           if key not in {"test_execution", "covered_tests", "covered_test_cases"}}
    raw["type"] = "custom"
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_TEST_EXECUTION"):
        validate(raw, snapshot, False)


def test_custom_coverage_cannot_reuse_command_only_measurement(tmp_path, monkeypatch):
    from harness.evidence_validator import ReuseRequest, can_reuse_evidence
    record, snapshot = collect(tmp_path, monkeypatch, "def test_required():\n    assert True\n",
                               "tests/test_actual.py::test_required")
    # Unit predicate input only: nominal label cannot bypass actual-coverage admission.
    # No claim that custom --covered-test is supported by the native CLI.
    record = {**record, "type": "custom"}
    validate(record, snapshot, True)
    request = ReuseRequest("custom", record["command"], "related", tuple(record["covered_tests"]), None, None, None)
    assert can_reuse_evidence(record, request, current_head=snapshot.head,
                             current_workspace=snapshot.fingerprint, current_runtime=record["runtime"]) is True
    raw = {key: value for key, value in record.items() if key != "test_execution"}
    assert can_reuse_evidence(raw, request, current_head=snapshot.head,
                             current_workspace=snapshot.fingerprint, current_runtime=raw["runtime"]) is False


@pytest.mark.parametrize("selector,success", [
    ("tests/test_actual.py::test_required", True), ("tests/test_actual.py", False),
])
def test_unrelated_xfail_does_not_poison_exact_passed_target(tmp_path, monkeypatch, selector, success):
    record, snapshot = collect(tmp_path, monkeypatch,
        "import pytest\n@pytest.mark.xfail(reason='unrelated expected failure')\ndef test_other():\n    assert False\ndef test_required():\n    assert True\n",
        selector)
    if success:
        validate(record, snapshot, True)
    else:
        with pytest.raises(EvidenceValidationError, match="EVIDENCE_TEST_EXECUTION"):
            validate(record, snapshot, True)


@pytest.mark.parametrize("body", [
    "import pytest\ndef test_required():\n    with pytest.raises(ValueError):\n        pass\n",
    "import pytest\ndef test_required():\n    pytest.fail('expected product condition')\n",
])
def test_pytest_expectation_failure_is_assertion_red(tmp_path, monkeypatch, body):
    record, snapshot = collect(tmp_path, monkeypatch, body, "tests/test_actual.py::test_required")
    validate(record, snapshot, False)


@pytest.mark.parametrize("phase,body,success", [
    ("green", "def test_required():\n    assert True\n", True),
    ("red", "def test_required():\n    assert False\n", False),
])
def test_phase_claim_captures_execution_even_with_build_label(tmp_path, monkeypatch, phase, body, success):
    record, snapshot = collect(tmp_path, monkeypatch, body, "tests/test_actual.py::test_required",
                               kind="build", cover=False, phase=phase)
    assert "test_execution" in record
    validate(record, snapshot, success)


def validate(record, snapshot, success):
    validate_evidence(record, current_head=snapshot.head,
                      current_workspace=snapshot.fingerprint, expected_success=success)


@pytest.mark.parametrize("body,selector,options", [
    ("def test_required():\n    assert False\ndef test_other():\n    pass\n",
     "tests/test_actual.py::test_required", "-k test_other"),
    ("def test_required():\n    pass\ndef test_other():\n    pass\n",
     "tests/test_actual.py", "-k test_other"),
    ("def test_required():\n    pass\n", "tests/test_actual.py", "--collect-only"),
    ("import pytest\n@pytest.mark.skip(reason='fixture')\ndef test_required():\n    pass\n",
     "tests/test_actual.py::test_required", ""),
])
def test_unexecuted_or_incomplete_selection_is_not_green(tmp_path, monkeypatch, body, selector, options):
    record, snapshot = collect(tmp_path, monkeypatch, body, selector, options)
    assert record["exit_code"] == 0
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_TEST_EXECUTION"):
        validate(record, snapshot, True)


@pytest.mark.parametrize("body", [
    "import _missing_execution_fixture_module_918\ndef test_required():\n    pass\n",
    "import pytest\n@pytest.fixture\ndef broken():\n    raise RuntimeError('setup')\ndef test_required(broken):\n    pass\n",
    "def test_required():\n    value = {}\n    value['risk']\n",
])
def test_collection_or_setup_error_is_not_product_red(tmp_path, monkeypatch, body):
    record, snapshot = collect(tmp_path, monkeypatch, body, "tests/test_actual.py", phase="red")
    assert record["exit_code"] != 0
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_TEST_EXECUTION"):
        validate(record, snapshot, False)


def test_expected_failing_pytest_child_does_not_invalidate_outer_test(tmp_path, monkeypatch):
    body = (
        "import subprocess, sys\nfrom pathlib import Path\n"
        "def test_required():\n"
        "    Path('.harness/child.py').write_text('def test_child():\\n    assert False\\n')\n"
        "    result = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '.harness/child.py'], capture_output=True)\n"
        "    assert result.returncode == 1\n"
    )
    record, snapshot = collect(tmp_path, monkeypatch, body, "tests/test_actual.py::test_required")
    assert record["exit_code"] == 0
    validate(record, snapshot, True)
    assert len(record["test_execution"]["runs"]) == 1


def test_reporter_does_not_shadow_subject_package(tmp_path, monkeypatch):
    from harness.execution_capture import run
    installed = tmp_path / "installed/harness"
    installed.mkdir(parents=True)
    (installed / "__init__.py").write_text("INSTALLED_FIXTURE = True\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_package.py").write_text("import harness\ndef test_subject():\n    assert harness.INSTALLED_FIXTURE\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(installed.parent))
    result, proof = run(f"{sys.executable} -B -m pytest -q -p no:cacheprovider tests/test_package.py", 30, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert proof is not None


def test_masked_shell_failure_is_not_green(tmp_path, monkeypatch):
    record, snapshot = collect(tmp_path, monkeypatch, "def test_required():\n    assert False\n",
                               "tests/test_actual.py::test_required", "|| true")
    assert record["exit_code"] == 0
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_TEST_EXECUTION"):
        validate(record, snapshot, True)


def test_custom_finding_cannot_bypass_red_execution_validation(tmp_path, monkeypatch):
    record, snapshot = collect(tmp_path, monkeypatch,
                               "import _missing_custom_finding_module\ndef test_required():\n    pass\n",
                               "tests/test_actual.py::test_required", phase="red", kind="custom")
    assert record["exit_code"] != 0
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_TEST_EXECUTION"):
        validate(record, snapshot, False)


@pytest.mark.parametrize("success", [True, False])
def test_actual_call_outcome_is_proof_and_legacy_record_is_not(tmp_path, monkeypatch, success):
    body = "def test_required():\n    assert " + str(success) + "\n"
    record, snapshot = collect(tmp_path, monkeypatch, body, "tests/test_actual.py::test_required",
                               phase="green" if success else "red")
    validate(record, snapshot, success)
    assert record.get("test_execution"), "collector must capture actual execution"
    legacy = deepcopy(record)
    legacy.pop("test_execution", None)
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_TEST_EXECUTION"):
        validate(legacy, snapshot, success)
    from harness.evidence_validator import EvidenceStatus, _projection
    projection = _projection(legacy, current_head=snapshot.head, current_workspace=snapshot.fingerprint,
                             expected_success=success)
    assert projection.status is EvidenceStatus.FAILED  # Historical measurement remains readable, not qualified.
    assert projection.code == "EVIDENCE_TEST_EXECUTION_INVALID"
