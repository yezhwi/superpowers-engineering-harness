"""Qualification grammar, not shell execution restriction or sandbox."""
import pytest

from harness.execution_capture import supported_command


@pytest.mark.parametrize("command", [
    "pytest tests/test_x.py", "/venv/bin/python3 -B -m pytest -q tests/test_x.py",
    "MODE=red /venv/bin/python -m pytest tests/test_x.py",
    "env MODE=red python3 -m pytest tests/test_x.py",
    "sh -lc 'cd backend && python3 -B -m pytest tests/test_x.py'",
    "cd backend && pytest tests/test_x.py", "pytest 'tests/test_x.py::test_x[a;b]'",
    "cd backend && env MODE=red pytest tests/test_x.py",
    "env MODE=red sh -lc 'pytest tests/test_x.py'",
    "sh -lc 'cd backend && MODE=red python -m pytest tests/test_x.py'",
    "cd backend && cd nested && env MODE=red python -m pytest tests/test_x.py",
])
def test_single_transparent_pytest_command_supported(command):
    assert supported_command(command)


@pytest.mark.parametrize("command", [
    "false; pytest tests/test_x.py", "false\npytest tests/test_x.py",
    "pytest tests/test_x.py || true", "false | pytest tests/test_x.py",
    "pytest tests/test_x.py & wait", "false && pytest tests/test_x.py",
    "python -c 'import pytest; pytest.main()'", "sh -lc 'false; pytest tests/test_x.py'",
    "bash -c 'false || pytest tests/test_x.py'", "pytest $(false) tests/test_x.py",
    "pytest `false` tests/test_x.py", "pytest tests/test_x.py > output",
    "(pytest tests/test_x.py)", "pytest tests/test_x.py && pytest tests/test_y.py",
    "env -S 'python -m pytest'", "", "pytest 'unclosed", "sh -c 'pytest x' extra",
    "env", "cd nowhere &&", "MODE=red", "python -c pass", "python3.11 -I -m pytest",
    "printf hi && pytest x",
])
def test_unsupported_shell_remains_measurement_only(command):
    assert not supported_command(command)


@pytest.mark.parametrize("runner", ["pytest", "python3 -B -m pytest"])
@pytest.mark.parametrize("option", ["-n 2", "-n2", "--numprocesses=2", "--numprocesses auto",
                                     "--dist=load", "--tx ssh=host", "-d"])
def test_worker_and_transport_options_are_measurements_only(runner, option):
    assert not supported_command(f"{runner} {option} tests/test_x.py")


def test_shell_wrapper_recursion_is_bounded():
    import shlex

    command = "pytest tests/test_x.py"
    for _ in range(10):
        command = "sh -c " + shlex.quote(command)
    assert not supported_command(command)
